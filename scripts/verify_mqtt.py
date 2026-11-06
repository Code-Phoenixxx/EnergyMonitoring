"""Verification utility to listen on factory/+/telemetry and display formatted live messages."""

import argparse
import json
import logging
import platform
import socket
import subprocess
import sys
import time
import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mqtt_verifier")


def resolve_broker_host(target_host: str, port: int) -> str:
    """Resolve reachable broker host, with automatic Windows WSL IP detection if needed."""
    try:
        with socket.create_connection((target_host, port), timeout=0.5):
            return target_host
    except (OSError, socket.error):
        pass

    if platform.system() == "Windows" and target_host in ("localhost", "127.0.0.1"):
        try:
            wsl_out = subprocess.check_output(["wsl", "hostname", "-I"], text=True, timeout=2).strip()
            if wsl_out:
                wsl_ip = wsl_out.split()[0]
                with socket.create_connection((wsl_ip, port), timeout=0.5):
                    logger.info(f"Target host '{target_host}:{port}' redirected to WSL IP '{wsl_ip}:{port}'")
                    return wsl_ip
        except Exception:
            pass

    return target_host


def on_connect(client, userdata, flags, rc, properties=None):
    rc_val = getattr(rc, "value", rc)
    if rc_val == 0:
        logger.info("Connected to MQTT Broker. Subscribing to 'factory/+/telemetry'...")
        client.subscribe("factory/+/telemetry", qos=1)
    else:
        logger.error(f"Failed to connect, rc={rc_val}")


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        print("\n" + "=" * 65)
        print(f" TOPIC: {msg.topic}")
        print("=" * 65)
        print(f" Machine ID    : {data.get('machine_id')}")
        print(f" Timestamp     : {data.get('timestamp')}")
        print(f" State         : {data.get('state')}")
        print(f" Power (kW)    : {data.get('power_kw'):.3f} kW")
        print(f" Voltage       : {data.get('voltage'):.2f} V")
        print(f" Current       : {data.get('current'):.2f} A")
        print(f" Power Factor  : {data.get('power_factor'):.3f}")
        print(f" Cumulative kWh: {data.get('energy_kwh'):.4f} kWh")
        print("=" * 65)
        userdata["count"] += 1
    except Exception as e:
        logger.error(f"Error parsing message payload: {e}")


def main():
    parser = argparse.ArgumentParser(description="MQTT Factory Telemetry Verification Listener")
    parser.add_argument("--broker", default="127.0.0.1", help="MQTT Broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker port")
    parser.add_argument("--count", type=int, default=6, help="Exit after receiving N messages")
    parser.add_argument("--timeout", type=int, default=15, help="Timeout in seconds")
    parser.add_argument(
        "--run-sim",
        action="store_true",
        help="Automatically trigger a simulator run to generate sample messages",
    )
    args = parser.parse_args()

    # If --run-sim is specified, start a simulator cycle in background
    sim_proc = None
    if args.run_sim:
        sim_cmd = [
            sys.executable,
            "-m",
            "simulator.main",
            "--step-count",
            "1",
            "--speedup",
            "10.0",
        ]
        logger.info("Spawning simulator subprocess for sample generation...")
        sim_proc = subprocess.Popen(sim_cmd)

    state = {"count": 0}

    try:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="verifier_listener",
            userdata=state,
        )
    except AttributeError:
        client = mqtt.Client(client_id="verifier_listener", userdata=state)

    client.on_connect = on_connect
    client.on_message = on_message

    broker_host = resolve_broker_host(args.broker, args.port)
    logger.info(f"Connecting to broker {broker_host}:{args.port}...")
    try:
        client.connect(broker_host, args.port, 60)
        client.loop_start()

        start = time.time()
        while state["count"] < args.count:
            if time.time() - start > args.timeout:
                logger.warning(f"Timeout reached ({args.timeout}s). Received {state['count']} messages.")
                break
            time.sleep(0.2)

        client.loop_stop()
        client.disconnect()
        if sim_proc:
            sim_proc.wait(timeout=5)
        logger.info(f"Verification complete. Total messages captured: {state['count']}")
    except Exception as e:
        logger.error(f"Could not connect or listen to MQTT broker: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
