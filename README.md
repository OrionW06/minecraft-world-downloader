# Python World Downloader

This is a Python script to download Minecraft worlds.

## Prerequisites

- Python 3.8 or higher
- Pip

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/mircokroon/minecraft-world-downloader.git
   cd minecraft-world-downloader
   ```

2. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

```bash
python3 src/world_downloader.py --server <server_address> [options]
```

### Options

- `--server`, `-s`: The address of the remote server to connect to.
- `--token`, `-t`: Minecraft access token.
- `--username`, `-u`: Your Minecraft username.
- `--local-port`, `-l`: The port on which the world downloader's server will run (default: 25565).
- `--output`, `-o`: The world output directory (default: "world").
- `--disable-chunk-saving`: Disable writing chunks to disk.
- `--clear-settings`: Clear settings by deleting the config.json file, then exit.
