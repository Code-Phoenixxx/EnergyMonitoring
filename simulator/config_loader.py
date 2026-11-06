"""Configuration loader for factory simulator and machine specifications."""

import logging
from pathlib import Path
from typing import Any, Dict
import yaml

from simulator.models import MachineConfig, StateProfile

logger = logging.getLogger(__name__)


def load_yaml(file_path: Path) -> Dict[str, Any]:
    """Load and parse a YAML file safely.

    Args:
        file_path: Absolute or relative Path object to YAML configuration.

    Returns:
        Dictionary representation of parsed YAML.

    Raises:
        FileNotFoundError: If the specified configuration file does not exist.
        yaml.YAMLError: If YAML syntax parsing fails.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        logger.debug(f"Successfully loaded configuration from {file_path}")
        return data or {}


def load_machines_config(config_dir: Path) -> Dict[str, MachineConfig]:
    """Load machine specifications from config/machines.yaml.

    Args:
        config_dir: Directory containing config YAML files.

    Returns:
        Mapping of machine_id to validated MachineConfig models.
    """
    machines_file = config_dir / "machines.yaml"
    raw_data = load_yaml(machines_file)
    raw_machines = raw_data.get("machines", {})

    machines: Dict[str, MachineConfig] = {}
    for mid, mdata in raw_machines.items():
        states = {}
        for sname, svals in mdata.get("states", {}).items():
            # In YAML 1.1, OFF and ON can be parsed as False/True booleans
            if sname is False:
                key_name = "OFF"
            elif sname is True:
                key_name = "ON"
            else:
                key_name = str(sname).upper()
            states[key_name] = StateProfile(**svals)

        machines[mid] = MachineConfig(
            machine_id=mdata.get("machine_id", mid),
            name=mdata.get("name", mid),
            category=mdata.get("category", "General"),
            rated_power_kw=float(mdata["rated_power_kw"]),
            nominal_voltage_v=float(mdata.get("nominal_voltage_v", 415.0)),
            phase_count=int(mdata.get("phase_count", 3)),
            nominal_power_factor=float(mdata.get("nominal_power_factor", 0.85)),
            states=states,
            faults=mdata.get("faults", {})
        )

    logger.info(f"Loaded specifications for {len(machines)} machines from {machines_file}")
    return machines


def load_simulator_config(config_dir: Path) -> Dict[str, Any]:
    """Load simulator parameters, shift configurations, and MQTT settings."""
    sim_file = config_dir / "simulator.yaml"
    return load_yaml(sim_file)
