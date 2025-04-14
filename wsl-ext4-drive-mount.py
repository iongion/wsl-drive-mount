"""
# WSL ext4 drive mount utility

- Able to automatically mount `\\.\PHYSICALDRIVE{X}` to a desired path
- Mounted with normal user permissions (you don't need root)

## Setup

Create a `settings.json` next to the python script itself with the following:

### Program settings

- `Sudo`: the native sudo for Windows 11 or gsudo from <https://gerardog.github.io/gsudo/> `winget install gsudo` (gsudo can cache UAC prompts)
- `Distribution`: Your distribution of choice `wsl.exe -l -v`
- `User`: Your WSL distribution user (normal user, not root)
- `Devices`: An array of devices to be mounted

### Devices configuration

- `DeviceId` - obtained with `wmic diskdrive list brief`, where its value is the numeric part of `\\.\PHYSICALDRIVE{DeviceId}`
- `Label` - is the ext4 partition label to be mounted
- `MountPoint` - where to mount
- `Sentinel` - a file on the mounted volume that allows the script to check if the volume is mounted or not

```json
{
	"Sudo": "gsudo",
	"Distribution": "Ubuntu-24.04",
	"User": "ubuntu",
	"Devices": [
		{
			"DeviceId": "1",
			"Label": "Work",
			"MountPoint": "/home/ubuntu/Backup",
			"Sentinel": "Workspace"
		}
	]
}
```

### Usage

1. `python3 wsl-mount.py -m mount` for mounting
2. `python3 wsl-mount.py -m unmount` for un-mounting

"""

import argparse
import subprocess
import os
import time
import json
import logging
from pathlib import Path

# Configuration
PROJECT_HOME = os.path.dirname(__file__)
SETTINGS_PATH = os.path.join(PROJECT_HOME, "settings.json")
SETTINGS = json.loads(Path(SETTINGS_PATH).read_text())
DISTRIBUTION = SETTINGS.get("Distribution", "Ubuntu-24.04")
SUDO_COMMAND = SETTINGS.get("Sudo", "sudo")
USER = SETTINGS.get("User", "ubuntu")
DEVICES = SETTINGS.get("Devices", [])

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_powershell_command(command):
    """Executes a PowerShell command and returns the JSON output."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"Error executing PowerShell command: {e}")
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON: {e}\nPowerShell output: {result.stdout}")
    except FileNotFoundError:
        logging.error("powershell.exe not found. Ensure it's in your PATH.")
    return None

def get_physical_disks_info():
    """Retrieves physical disk information from Windows using PowerShell."""
    powershell_command = [
        "powershell.exe",
        "-Command",
        "Get-PhysicalDisk | Select-Object DeviceId,SerialNumber,FriendlyName,ObjectId | Sort-Object { [int]$_.DeviceId } | ConvertTo-JSON",
    ]
    items = run_powershell_command(powershell_command)
    if not items:
        return []

    usable_items = []
    for item in items:
        object_id = item["ObjectId"]
        parts = object_id.split("=")
        if len(parts) > 1:
            decoded = json.loads(parts[1])
            identifiers = decoded.split(":PD:")
            if len(identifiers) > 1:
                item["Windows_ObjectId"] = identifiers[0].replace("{", "").replace("}", "")
                item["Windows_UUID"] = identifiers[1].replace("{", "").replace("}", "")
                del item["ObjectId"]
                usable_items.append(item)
    return usable_items

def get_mountable_disks():
    """Filters and enriches physical disk information with mountable device details."""
    devices_id_map = {int(device.get("DeviceId")): device for device in DEVICES}
    disks = get_physical_disks_info()
    mountable_disks = []
    for disk in disks:
        disk_id = int(disk["DeviceId"])
        if disk_id in devices_id_map:
            disk["Drive"] = f"\\\\.\\PHYSICALDRIVE{disk_id}"
            disk.update(devices_id_map[disk_id])
            mountable_disks.append(disk)
    return mountable_disks

def run_wsl_command(command):
    """Executes a WSL command and returns the output."""
    logging.info(f"Executing WSL command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result

def get_wsl_devices(distribution):
    """Retrieves device information from WSL using blkid."""
    logging.info("Getting WSL devices...")
    command = ["wsl", "--distribution", distribution, "-u", "root", "blkid"]
    output = run_wsl_command(command).stdout.strip()
    logging.debug(f"WSL devices raw: {output}")

    device_data = []
    for line in output.splitlines():
        parts = line.split(":")
        device_info = {"device": parts[0].strip()}
        if len(parts) > 1:
            attributes = parts[1].split()
            for attribute in attributes:
                if "=" in attribute:
                    key, value = attribute.split("=", 1)
                    device_info[key.strip('"')] = value.strip('"')
        device_data.append(device_info)
    return device_data

def ensure_wsl_is_running(distribution):
    """Ensures the specified WSL distribution is running with retries."""
    logging.info(f"Checking if WSL distribution {distribution} is running...")
    command = ["wsl.exe", "--distribution", distribution, "--exec", "echo", "WSL"]
    max_attempts = 5
    attempt = 0
    for attempt in range(max_attempts):
        output = subprocess.run(command, capture_output=True, text=True, check=False)
        if output.returncode == 0:
            logging.info(f"WSL distribution {distribution} is running.")
            return True

        logging.warning(f"Attempt {attempt + 1} failed to start WSL distribution {distribution}: {output.stderr.decode()}")
        if attempt < max_attempts:  # Don't sleep after the last attempt
            logging.info("Retrying in 1 second...")
            time.sleep(1)

    logging.error(f"Failed to start WSL distribution {distribution} after 5 attempts.")
    return False

def mount_wsl_drive_path(drive_path):
    """Mounts a physical drive into WSL."""
    logging.info(f"Mounting WSL drive path: {drive_path}")
    command = [SUDO_COMMAND, "wsl.exe", "--mount", drive_path, "--bare"]
    output = run_wsl_command(command)
    if output.returncode == 0:
        logging.info(f"Successfully mounted WSL drive path: {drive_path}")
        return True

    output_str = json.loads(json.dumps(output.stdout.decode("utf-8", errors="replace").replace("\u0000", "").strip()))
    if "WSL_E_DISK_ALREADY_ATTACHED" in output_str:
        logging.info("WSL drive already attached.")
        return True

    logging.error(f"Error mounting WSL drive: {output_str}")
    return False

def mount_wsl_drive_volume(drive):
    """Mounts a volume from a physical drive within WSL."""
    drive_id = drive["DeviceId"]
    drive_path = drive["Drive"]
    device_name = drive["device"]
    file_system_type = drive.get("TYPE", "ext4")
    mount_point = drive.get("MountPoint", f"/mnt/drive-{drive_id}")
    mount_point_wsl = mount_point.replace("/", "\\")
    mount_path_wsl = f"\\\\wsl.localhost\\{DISTRIBUTION}{mount_point_wsl}"
    sentinel_path = f"{mount_path_wsl}\\{drive['Sentinel']}"

    if not ensure_wsl_is_running(DISTRIBUTION):
        return False

    if not os.path.exists(sentinel_path):
        logging.info(f"Sentinel file {sentinel_path} not found. Ensuring mount point exists...")
        run_wsl_command(["wsl.exe", "--distribution", DISTRIBUTION, "-u", "root", "mkdir", "-p", mount_point])
        run_wsl_command(["wsl.exe", "--distribution", DISTRIBUTION, "-u", "root", "chown", f"{USER}:{USER}", mount_point])
        run_wsl_command(["wsl.exe", "--distribution", DISTRIBUTION, "-u", "root", "chmod", "755", mount_point])
        logging.info(f"Mounting WSL drive volume: {drive_path} to {mount_point}")
        command = ["wsl.exe", "--distribution", DISTRIBUTION, "-u", "root", "mount", "-t", file_system_type, device_name, mount_point]
        output = run_wsl_command(command)
        if output.returncode != 0:
            logging.error(f"Error mounting WSL drive volume: {output.stderr.decode()}")
            return False
        logging.info(f"Mounted WSL drive volume: {drive_path} to {mount_point}")
    return True

def unmount_wsl_drive_volume(drive):
    """Unmounts a volume from a physical drive within WSL."""
    drive_id = drive["DeviceId"]
    drive_path = drive["Drive"]
    mount_point = drive.get("MountPoint", f"/mnt/drive-{drive_id}")
    mount_point_wsl = mount_point.replace("/", "\\")
    sentinel_path = f"\\\\wsl.localhost\\{DISTRIBUTION}{mount_point_wsl}\\{drive['Sentinel']}"

    if os.path.exists(sentinel_path):
        logging.info(f"Unmounting WSL drive volume: {drive_path} from {mount_point}")
        command = ["wsl.exe", "--distribution", DISTRIBUTION, "-u", "root", "--exec", "umount", mount_point]
        output = run_wsl_command(command)
        if output.returncode != 0:
            logging.error(f"Error unmounting WSL drive volume: {output.stdout.decode()}")
        logging.info(f"Unmounted WSL drive volume: {drive_path} from {mount_point}")

    logging.info(f"Unmounting WSL drive: {drive_path}")
    command = [SUDO_COMMAND, "wsl.exe", "--distribution", DISTRIBUTION, "--unmount", drive_path]
    output = run_wsl_command(command)
    if output.returncode != 0:
        logging.error(f"Error unmounting WSL drive: {output.stdout.decode()}")

    logging.info(f"Unmounted WSL drive and volume: {drive_path} from {mount_point}")

def get_matching_mountable_disks():
    """Retrieves mountable disks and matches them with WSL devices."""
    mountable_disks = get_mountable_disks()
    if not ensure_wsl_is_running(DISTRIBUTION):
        logging.error(f"WSL {DISTRIBUTION} distribution is not running.")
        return []

    wsl_devices = get_wsl_devices(DISTRIBUTION)
    logging.debug(f"Mountable disks: {json.dumps(mountable_disks, indent=2)}")
    logging.debug(f"WSL Devices: {json.dumps(wsl_devices, indent=2)}")

    if not mountable_disks:
        logging.info("No mountable disks found.")
        return []

    for disk in mountable_disks:
        if mount_wsl_drive_path(disk["Drive"]):
            logging.info(f"{disk['Label']} Drive {disk['Drive']} mounted successfully.")

    time.sleep(3)
    wsl_devices = get_wsl_devices(DISTRIBUTION)
    matching_disks = []
    for disk in mountable_disks:
        for device in wsl_devices:
            if disk["Label"] == device.get("LABEL"):
                disk.update(device)
                matching_disks.append(disk)
                break

    if not matching_disks:
        logging.info("No matching mountable disks found.")
    return matching_disks

def mount_all_disks():
    """Mounts all matching mountable disks."""
    matching_disks = get_matching_mountable_disks()
    logging.info("Mounting volumes of matching mountable disks...")
    for disk in matching_disks:
        mount_wsl_drive_volume(disk)

def unmount_all_disks():
    """Unmounts all mountable disks."""
    mountable_disks = get_mountable_disks()
    logging.info("Unmounting volumes of mountable disks...")
    for disk in mountable_disks:
        unmount_wsl_drive_volume(disk)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WSL Mount Utility")
    parser.add_argument("-m", "--mode", type=str, choices=["mount", "unmount"], default="mount", help="Mode: mount or unmount")
    args = parser.parse_args()

    if args.mode == "mount":
        logging.info("Mounting WSL drives...")
        mount_all_disks()
    elif args.mode == "unmount":
        logging.info("Unmounting WSL drives...")
        unmount_all_disks()
