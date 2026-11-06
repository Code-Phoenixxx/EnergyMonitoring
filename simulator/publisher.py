"""MQTT client publisher and verification subscriber for machine telemetry."""

import json
import logging
import platform
import socket
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional
import paho.mqtt.client as mqtt

from simulator.models import MachineTelemetry

logger = logging.getLogger(__name__)


_CACHED_WSL_IP = None


def get_wsl_ip() -> str | None:
    """Retrieve and cache WSL2 virtual IP address on Windows."""
    global _CACHED_WSL_IP
    if _CACHED_WSL_IP is not None:
        return _CACHED_WSL_IP
    if platform.system() == "Windows":
        try:
            wsl_out = subprocess.check_output(["wsl", "hostname", "-I"], text=True, timeout=4).strip()
            if wsl_out:
                _CACHED_WSL_IP = wsl_out.split()[0]
                return _CACHED_WSL_IP
        except Exception:
            pass
    return None


def resolve_broker_host(target_host: str, port: int) -> str:
    """Resolve reachable broker host, with automatic Windows WSL IP detection if needed."""
    # If on Windows and target is localhost/127.0.0.1, prioritize WSL IP
    if platform.system() == "Windows" and target_host in ("localhost", "127.0.0.1"):
        wsl_ip = get_wsl_ip()
        if wsl_ip:
            try:
                with socket.create_connection((wsl_ip, port), timeout=1.0):
                    logger.info(f"Target host '{target_host}:{port}' redirected to WSL IP '{wsl_ip}:{port}'")
                    return wsl_ip
            except Exception:
                pass

    # Test if target_host is immediately reachable
    try:
        with socket.create_connection((target_host, port), timeout=0.5):
            return target_host
    except (OSError, socket.error):
        pass

    return target_host


class TelemetryPublisher:
    """Publishes machine telemetry payloads to MQTT broker."""

    def __init__(
        self,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        client_id: str = "simulator_publisher",
        topic_template: str = "factory/{machine_id}/telemetry",
        qos: int = 1,
    ) -> None:
        """Initialize TelemetryPublisher with broker connection details."""
        self.broker_host = resolve_broker_host(broker_host, broker_port)
        self.broker_port = broker_port
        self.client_id = client_id
        self.topic_template = topic_template
        self.qos = qos
        self.is_connected = False

        # Support both paho-mqtt v1 and v2 API
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
            )
        except AttributeError:
            self.client = mqtt.Client(client_id=client_id)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client: Any, userdata: Any, *args: Any, **kwargs: Any) -> None:
        """MQTT on_connect callback handler."""
        rc = args[1] if len(args) > 1 else (args[0] if len(args) > 0 else 0)
        rc_code = getattr(rc, "value", rc)
        if rc_code == 0:
            self.is_connected = True
            logger.info(f"Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
        else:
            self.is_connected = False
            logger.warning(f"Failed to connect to MQTT broker, return code: {rc_code}")

    def _on_disconnect(self, client: Any, userdata: Any, *args: Any, **kwargs: Any) -> None:
        """MQTT on_disconnect callback handler."""
        self.is_connected = False
        logger.warning(f"Disconnected from MQTT broker at {self.broker_host}:{self.broker_port}")

    def connect(self, retry_attempts: int = 5, retry_delay_seconds: float = 2.0) -> bool:
        """Establish connection to MQTT broker with automatic retries."""
        for attempt in range(1, retry_attempts + 1):
            try:
                logger.info(
                    f"Attempting connection to MQTT broker {self.broker_host}:{self.broker_port} "
                    f"(Attempt {attempt}/{retry_attempts})..."
                )
                self.client.connect(self.broker_host, self.broker_port, keepalive=60)
                self.client.loop_start()
                # Wait briefly for connection handshake
                for _ in range(10):
                    if self.is_connected:
                        return True
                    time.sleep(0.1)
                return True
            except Exception as e:
                logger.warning(f"Connection attempt {attempt} failed: {e}")
                if attempt < retry_attempts:
                    time.sleep(retry_delay_seconds)

        logger.error(f"Could not connect to MQTT broker after {retry_attempts} attempts.")
        return False

    def publish(self, telemetry: MachineTelemetry) -> bool:
        """Serialize and publish machine telemetry to the designated MQTT topic.

        Args:
            telemetry: Validated MachineTelemetry object.

        Returns:
            True if publish request was queued successfully, False otherwise.
        """
        topic = self.topic_template.format(machine_id=telemetry.machine_id)
        payload = telemetry.model_dump_json()

        result = self.client.publish(topic, payload, qos=self.qos)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.debug(f"Published to {topic}: {payload}")
            return True
        else:
            logger.error(f"Failed to publish to {topic}, MQTT error code: {result.rc}")
            return False

    def disconnect(self) -> None:
        """Gracefully disconnect from MQTT broker and stop background network loop."""
        try:
            self.client.loop_stop()
            self.client.disconnect()
            self.is_connected = False
            logger.info("TelemetryPublisher disconnected cleanly.")
        except Exception as e:
            logger.debug(f"Error during disconnect: {e}")


class TelemetrySubscriber:
    """Verification listener subscribed to factory/+/telemetry."""

    def __init__(
        self,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        topic: str = "factory/+/telemetry",
    ) -> None:
        """Initialize subscriber to capture and inspect live telemetry messages."""
        self.broker_host = resolve_broker_host(broker_host, broker_port)
        self.broker_port = broker_port
        self.topic = topic
        self.received_messages: List[Dict[str, Any]] = []

        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id="telemetry_verifier",
            )
        except AttributeError:
            self.client = mqtt.Client(client_id="telemetry_verifier")

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client: Any, userdata: Any, *args: Any, **kwargs: Any) -> None:
        """Subscribe to target topic upon successful connection."""
        self.client.subscribe(self.topic, qos=1)
        logger.info(f"TelemetrySubscriber subscribed to topic: {self.topic}")

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Parse incoming telemetry payload and store for inspection."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            self.received_messages.append({"topic": msg.topic, "payload": payload})
            logger.info(f"[RECEIVED on {msg.topic}] {payload}")
        except Exception as e:
            logger.error(f"Failed to decode message on {msg.topic}: {e}")

    def start(self) -> None:
        """Connect and start receiving messages in background."""
        self.client.connect(self.broker_host, self.broker_port, keepalive=60)
        self.client.loop_start()

    def stop(self) -> None:
        """Stop receiving messages and disconnect."""
        self.client.loop_stop()
        self.client.disconnect()
