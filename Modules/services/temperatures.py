# Temperature collection service for dashboard metrics.
import os
import sys
import time
import threading
import platform
import subprocess
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import psutil
import requests

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Modules.core.common import setup_module_logging

logger: logging.Logger = setup_module_logging("TemperatureService")


@dataclass
class TemperatureSnapshot:
	text: str
	source: str
	collected_at: float
	ok: bool = True


class TemperatureProvider:
	name = "provider"

	def collect(self) -> Optional[str]:
		return None


class LocalWindowsTemperatureProvider(TemperatureProvider):
	name = "local"

	def collect(self) -> Optional[str]:
		lines: List[str] = []

		# Primary path: psutil temperatures and fan RPM if exposed by hardware drivers.
		try:
			sensor_data = psutil.sensors_temperatures(fahrenheit=False) or {}
			for device_name, entries in sensor_data.items():
				device_header_added = False
				for index, entry in enumerate(entries):
					current = getattr(entry, "current", None)
					if current is None:
						continue

					if not device_header_added:
						lines.append(f"{device_name}:")
						device_header_added = True

					label = getattr(entry, "label", None) or f"Sensor {index + 1}"
					high = getattr(entry, "high", None)
					critical = getattr(entry, "critical", None)
					extras: List[str] = []
					if high is not None:
						extras.append(f"high {high:.1f}C")
					if critical is not None:
						extras.append(f"crit {critical:.1f}C")
					suffix = f" ({', '.join(extras)})" if extras else ""
					lines.append(f"  {label}: {current:.1f}C{suffix}")
		except Exception as e:
			logger.debug(f"psutil temperature read failed: {e}")

		# Fan checks for local machine support (when provided by platform/drivers).
		try:
			fan_data = psutil.sensors_fans() or {}
			if fan_data:
				lines.append("Fans:")
				for fan_group, entries in fan_data.items():
					for index, entry in enumerate(entries):
						label = getattr(entry, "label", None) or f"Fan {index + 1}"
						current = getattr(entry, "current", None)
						if current is None:
							continue
						lines.append(f"  {fan_group}/{label}: {int(current)} RPM")
		except Exception as e:
			logger.debug(f"psutil fan read failed: {e}")

		if lines:
			return "\n".join(lines)

		# Fallback path for Windows thermal zones.
		if platform.system() != "Windows":
			return None

		try:
			startupinfo = subprocess.STARTUPINFO()
			startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
			startupinfo.wShowWindow = 0

			result = subprocess.run(
				[
					"wmic",
					"/namespace:\\\\root\\wmi",
					"PATH",
					"MSAcpi_ThermalZoneTemperature",
					"get",
					"InstanceName,CurrentTemperature",
					"/format:csv",
				],
				capture_output=True,
				text=True,
				timeout=6,
				startupinfo=startupinfo,
				creationflags=subprocess.CREATE_NO_WINDOW,
			)

			if result.returncode != 0 or not result.stdout.strip():
				return None

			csv_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
			thermal_lines: List[str] = []
			for line in csv_lines[1:]:
				parts = [p.strip() for p in line.split(",")]
				if len(parts) < 3:
					continue
				instance_name = parts[1] or "Thermal Zone"
				try:
					raw_temp = float(parts[2])
					celsius = (raw_temp / 10.0) - 273.15
				except Exception:
					continue
				thermal_lines.append(f"{instance_name}: {celsius:.1f}C")

			if thermal_lines:
				return "\n".join(thermal_lines)
		except Exception as e:
			logger.debug(f"WMI temperature read failed: {e}")

		return None


class _RedfishThermalProvider(TemperatureProvider):
	vendor_name = "Redfish"

	def __init__(
		self,
		host: str,
		username: str,
		password: str,
		verify_tls: bool = False,
		timeout_seconds: float = 4.0,
	) -> None:
		self.host = str(host or "").strip()
		self.username = username
		self.password = password
		self.verify_tls = bool(verify_tls)
		self.timeout_seconds = max(1.0, float(timeout_seconds or 4.0))

	def _base_url(self) -> str:
		host = self.host
		if host.startswith("http://") or host.startswith("https://"):
			return host.rstrip("/")
		return f"https://{host}"

	def _request_json(self, path: str) -> Optional[Dict[str, Any]]:
		url = f"{self._base_url()}{path}"
		try:
			response = requests.get(
				url,
				auth=(self.username, self.password),
				verify=self.verify_tls,
				timeout=self.timeout_seconds,
				headers={"Accept": "application/json"},
			)
			if not response.ok:
				logger.debug(f"{self.vendor_name} request failed {response.status_code}: {url}")
				return None
			return response.json()
		except Exception as e:
			logger.debug(f"{self.vendor_name} request error ({url}): {e}")
			return None

	def collect(self) -> Optional[str]:
		if not self.host or not self.username or not self.password:
			return None

		lines: List[str] = []

		chassis = self._request_json("/redfish/v1/Chassis")
		if not chassis:
			return None

		members = chassis.get("Members") or []
		for member in members:
			member_uri = str(member.get("@odata.id") or "").strip()
			if not member_uri:
				continue

			thermal = self._request_json(f"{member_uri}/Thermal")
			if not thermal:
				continue

			temps = thermal.get("Temperatures") or []
			fans = thermal.get("Fans") or []

			if temps:
				lines.append(f"{self.vendor_name} Temperatures:")
				for temp in temps:
					name = temp.get("Name") or temp.get("SensorNumber") or "Sensor"
					reading = temp.get("ReadingCelsius")
					if reading is None:
						continue
					upper = temp.get("UpperThresholdCritical")
					suffix = f" (crit {upper}C)" if upper is not None else ""
					lines.append(f"  {name}: {float(reading):.1f}C{suffix}")

			if fans:
				lines.append(f"{self.vendor_name} Fans:")
				for fan in fans:
					name = fan.get("Name") or fan.get("FanName") or "Fan"
					rpm = fan.get("Reading")
					units = fan.get("ReadingUnits") or "RPM"
					if rpm is None:
						continue
					lines.append(f"  {name}: {rpm} {units}")

		if lines:
			return "\n".join(lines)
		return None


class IloTemperatureProvider(_RedfishThermalProvider):
	name = "ilo"
	vendor_name = "HP iLO"


class IdracTemperatureProvider(_RedfishThermalProvider):
	name = "idrac"
	vendor_name = "Dell iDRAC"


def _setting(settings: Dict[str, Any], *keys: str, default: Any = None) -> Any:
	for key in keys:
		if key in settings:
			return settings[key]
	return default


class TemperatureService:
	def __init__(self, settings: Optional[Dict[str, Any]] = None, poll_interval_seconds: float = 10.0) -> None:
		self.settings = settings or {}
		self.poll_interval_seconds = max(2.0, float(poll_interval_seconds or 10.0))

		mode = str(_setting(self.settings, "temperatureMode", "temperature_mode", "auto") or "auto").strip().lower()
		self.mode = mode

		self.providers: List[TemperatureProvider] = []
		if mode in ("auto", "local", "windows"):
			self.providers.append(LocalWindowsTemperatureProvider())

		ilo_host = _setting(self.settings, "iloHost", "ilo_host", "")
		ilo_user = _setting(self.settings, "iloUsername", "ilo_username", "")
		ilo_pass = _setting(self.settings, "iloPassword", "ilo_password", "")
		if mode in ("auto", "ilo") and ilo_host and ilo_user and ilo_pass:
			self.providers.append(
				IloTemperatureProvider(
					host=str(ilo_host),
					username=str(ilo_user),
					password=str(ilo_pass),
					verify_tls=bool(_setting(self.settings, "iloVerifyTLS", "ilo_verify_tls", False)),
					timeout_seconds=float(_setting(self.settings, "iloTimeout", "ilo_timeout", 4.0) or 4.0),
				)
			)

		idrac_host = _setting(self.settings, "idracHost", "idrac_host", "")
		idrac_user = _setting(self.settings, "idracUsername", "idrac_username", "")
		idrac_pass = _setting(self.settings, "idracPassword", "idrac_password", "")
		if mode in ("auto", "idrac") and idrac_host and idrac_user and idrac_pass:
			self.providers.append(
				IdracTemperatureProvider(
					host=str(idrac_host),
					username=str(idrac_user),
					password=str(idrac_pass),
					verify_tls=bool(_setting(self.settings, "idracVerifyTLS", "idrac_verify_tls", False)),
					timeout_seconds=float(_setting(self.settings, "idracTimeout", "idrac_timeout", 4.0) or 4.0),
				)
			)

		self._lock = threading.Lock()
		self._stop_event = threading.Event()
		self._thread: Optional[threading.Thread] = None
		self._snapshot = TemperatureSnapshot(
			text="Temperature sensors not available",
			source="none",
			collected_at=time.time(),
			ok=False,
		)

	def start(self) -> None:
		if self._thread and self._thread.is_alive():
			return

		# Collect once immediately for boot/start visibility.
		self.refresh_once()

		self._stop_event.clear()
		self._thread = threading.Thread(target=self._run, daemon=True, name="TemperatureService")
		self._thread.start()

	def stop(self, timeout_seconds: float = 2.0) -> None:
		self._stop_event.set()
		if self._thread and self._thread.is_alive():
			self._thread.join(timeout=max(0.0, float(timeout_seconds or 0.0)))

	def _run(self) -> None:
		while not self._stop_event.is_set():
			self.refresh_once()
			self._stop_event.wait(self.poll_interval_seconds)

	def refresh_once(self) -> TemperatureSnapshot:
		provider_failures: List[str] = []

		for provider in self.providers:
			try:
				text = provider.collect()
				if text:
					snapshot = TemperatureSnapshot(
						text=text,
						source=provider.name,
						collected_at=time.time(),
						ok=True,
					)
					with self._lock:
						self._snapshot = snapshot
					return snapshot
			except Exception as e:
				provider_failures.append(f"{provider.name}: {e}")

		fallback_text = "Temperature sensors not available"
		if provider_failures and self.mode in ("ilo", "idrac"):
			fallback_text = f"Temperature source unreachable ({self.mode})"

		snapshot = TemperatureSnapshot(
			text=fallback_text,
			source="none",
			collected_at=time.time(),
			ok=False,
		)
		with self._lock:
			self._snapshot = snapshot
		return snapshot

	def get_latest_snapshot(self) -> TemperatureSnapshot:
		with self._lock:
			return self._snapshot


def create_temperature_service(settings: Optional[Dict[str, Any]] = None) -> TemperatureService:
	settings_dict = settings or {}
	poll_interval = float(_setting(settings_dict, "temperaturePollInterval", "temperature_poll_interval", 10.0) or 10.0)
	return TemperatureService(settings=settings_dict, poll_interval_seconds=poll_interval)
