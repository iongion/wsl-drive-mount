#  WSL ext4 drive mount utility

A suite of script and utilities to automate the mounting and unmount of ext4 physical drives in WSL using non-elevated user permissions

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
