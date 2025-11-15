# Minecraft World Downloader (Python Edition)

This is a Python-based tool for downloading Minecraft worlds from multiplayer servers. It acts as a proxy, intercepting the world data as you move around and saving it to a local `.mca` file.

## Prerequisites

*   Python 3.7+
*   The required Python packages, which can be installed via `pip`:
    ```bash
    pip install -r requirements.txt
    ```

## How to Install

1.  Clone this repository to your local machine.
2.  Install the required packages using the command above.

## How to Use

1.  Run the script with the following command, replacing the placeholders with your server and account information:
    ```bash
    python src/world_downloader.py --server <server_address> --username <your_username> --token <your_access_token>
    ```
2.  The script will start a local proxy server on port 25565.
3.  Open Minecraft and connect to `localhost:25565`.
4.  As you move around the world, the script will automatically download the chunks and save them to the `world` directory.

## Current Features

*   Connects to modern, online-mode Minecraft servers.
*   Downloads chunk data and saves it to local `.mca` files.
*   Supports SRV record lookup for server addresses.

## Known Issues

*   The chunk saving functionality is temporarily disabled while the modern chunk format is being reverse-engineered. The script will currently print raw NBT data to the console instead of saving chunks to a file.
*   Many of the advanced features from the original Java version of this tool have not yet been implemented.

## Contributing

Contributions are welcome! If you'd like to help with the development of this tool, please feel free to fork the repository and submit a pull request.
