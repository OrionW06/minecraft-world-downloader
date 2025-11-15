from Crypto.Cipher import AES
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
from Crypto.Random import get_random_bytes
import requests

class AESCipher:
    def __init__(self, key):
        self.key = key
        self.encryptor = AES.new(key, AES.MODE_CFB, iv=key, segment_size=8)
        self.decryptor = AES.new(key, AES.MODE_CFB, iv=key, segment_size=8)

    def encrypt(self, data):
        return self.encryptor.encrypt(data)

    def decrypt(self, data):
        return self.decryptor.decrypt(data)

import argparse
import json
import os
import sys
from pathlib import Path
import socket
import threading
import io
import nbtlib
import zlib
import time
import hashlib

def java_hex_digest(data):
    sha1 = hashlib.sha1()
    sha1.update(data)
    digest = sha1.digest()

    # Convert to a signed hex string
    is_negative = digest[0] & 0x80
    if is_negative:
        twos_complement = int.from_bytes(digest, 'big')
        inverted = twos_complement - (1 << (len(digest) * 8))
        return format(inverted, 'x')
    else:
        return digest.hex()

class Chunk:
    def __init__(self, data):
        self.data = data
        self.sections = nbtlib.List([])
        self.parse()

    def parse(self):
        data_io = io.BytesIO(self.data)
        for y in range(24): # Iterate through all possible sub-chunks
            block_count = int.from_bytes(data_io.read(2), 'big')
            bits_per_block = data_io.read(1)[0]

            if bits_per_block < 4:
                bits_per_block = 4

            if bits_per_block > 8: # Direct palette
                palette_length = 0
                palette = None
            else: # Indirect palette
                palette_length = read_varint(data_io)
                palette = []
                for _ in range(palette_length):
                    palette.append(read_varint(data_io))

            data_array_length = read_varint(data_io)
            data_array = data_io.read(data_array_length * 8)

            # Skip biome data
            bits_per_biome = data_io.read(1)[0]
            if bits_per_biome > 0:
                biome_palette_length = read_varint(data_io)
                for _ in range(biome_palette_length):
                    read_varint(data_io) # biome id
                biome_data_array_length = read_varint(data_io)
                data_io.read(biome_data_array_length * 8)


            if block_count > 0:
                self.sections.append(nbtlib.Compound({
                    'Y': nbtlib.Byte(y - 4), # Y is offset by 4 in modern versions
                    'BlockLight': nbtlib.ByteArray([0] * 2048),
                    'Blocks': nbtlib.ByteArray(self.get_blocks(bits_per_block, palette, data_array)),
                    'Data': nbtlib.ByteArray([0] * 2048),
                    'SkyLight': nbtlib.ByteArray([0] * 2048),
                }))

    def get_blocks(self, bits_per_block, palette, data_array):
        blocks = bytearray(4096)
        mask = (1 << bits_per_block) - 1

        for i in range(4096):
            start_bit = i * bits_per_block
            start_long = start_bit // 64
            end_long = (start_bit + bits_per_block - 1) // 64

            val = int.from_bytes(data_array[start_long*8:(end_long+1)*8], 'big')
            val >>= start_bit % 64
            val &= mask

            if palette is not None:
                if val < len(palette):
                    blocks[i] = palette[val]
            else:
                blocks[i] = val

        return bytes(blocks)

class RegionFile:
    def __init__(self, path):
        self.path = path
        if not self.path.exists():
            self.path.touch()
            with open(self.path, 'wb') as f:
                f.write(b'\x00' * 8192)

    def write_chunk(self, chunk_x, chunk_z, data):
        chunk_offset = 4 * ((chunk_x % 32) + (chunk_z % 32) * 32)

        with open(self.path, 'r+b') as f:
            f.seek(0, 2)
            file_size = f.tell()

            sector_offset = (file_size + 4095) // 4096

            f.seek(chunk_offset)
            f.write(sector_offset.to_bytes(3, 'big') + b'\x01')

            f.seek(file_size)
            compressed_data = zlib.compress(data)
            f.write(len(compressed_data).to_bytes(4, 'big') + b'\x02' + compressed_data)

def get_default_minecraft_path():
    if sys.platform == "win32":
        return Path(os.getenv("APPDATA")) / ".minecraft"
    elif sys.platform == "linux":
        return Path.home() / ".minecraft"
    elif sys.platform == "darwin":
        return Path.home() / "Library/Application Support/minecraft"
    else:
        return Path(".minecraft")

def read_fully(sock, length):
    data = b''
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            return None
        data += chunk
    return data

def read_varint(stream):
    result = 0
    num_read = 0
    while True:
        if isinstance(stream, io.BytesIO):
            byte_data = stream.read(1)
        else:
            byte_data = stream.recv(1)

        if not byte_data:
            return None

        byte = byte_data[0]
        value = byte & 0b01111111
        result |= value << (7 * num_read)
        num_read += 1

        if (byte & 0b10000000) == 0:
            break

    return result

class Packet:
    def __init__(self, packet_id, data):
        self.id = packet_id
        self.data = data

    @classmethod
    def read_packet(cls, sock, compression_threshold=-1, cipher=None):
        if cipher:
            # We can't know the length of the encrypted packet, so we just read
            data = sock.recv(4096)
            if not data:
                return None
            data = cipher.decrypt(data)
        else:
            packet_length = read_varint(sock)
            if packet_length is None:
                return None
            data = read_fully(sock, packet_length)
            if data is None:
                return None

        data_io = io.BytesIO(data)

        if compression_threshold != -1:
            data_length = read_varint(data_io)
            if data_length != 0:
                data = zlib.decompress(data_io.read())
            else:
                data = data_io.read()
            data_io = io.BytesIO(data)

        packet_id = read_varint(data_io)

        return cls(packet_id, data_io.read())

class Connection:
    def __init__(self, client_socket, remote_socket, args):
        self.client_socket = client_socket
        self.remote_socket = remote_socket
        self.state = "HANDSHAKE"
        self.args = args
        self.compression_threshold = -1
        self.client_cipher = None
        self.server_cipher = None

    def forward_data(self, source_socket, dest_socket, direction):
        try:
            while True:
                cipher = self.client_cipher if direction == "Server -> Client" else self.server_cipher

                packet = Packet.read_packet(source_socket, self.compression_threshold, cipher)
                if packet is None:
                    break

                self.handle_packet(packet, direction, dest_socket)

        except (ConnectionResetError, BrokenPipeError):
            print(f"[{direction}] Connection closed.")
        except Exception as e:
            print(f"[{direction}] An error occurred: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print(f"[{direction}] Closing sockets.")
            source_socket.close()
            dest_socket.close()

    def send_packet(self, packet, socket):
        packet_id_bytes = self.write_varint(packet.id)
        packet_data = packet_id_bytes + packet.data

        if self.compression_threshold != -1:
            if len(packet_data) >= self.compression_threshold:
                packet_data = self.write_varint(len(packet_data)) + zlib.compress(packet_data)
            else:
                packet_data = self.write_varint(0) + packet_data

        packet_length_bytes = self.write_varint(len(packet_data))

        data_to_send = packet_length_bytes + packet_data

        cipher = self.client_cipher if socket == self.client_socket else self.server_cipher

        if cipher:
            data_to_send = cipher.encrypt(data_to_send)

        socket.sendall(data_to_send)

    def handle_packet(self, packet, direction, dest_socket):
        if self.state == "HANDSHAKE":
            if direction == "Client -> Server" and packet.id == 0x00:
                data_io = io.BytesIO(packet.data)
                protocol_version = read_varint(data_io)

                server_address_len = read_varint(data_io)
                server_address = data_io.read(server_address_len).decode('utf-8')

                server_port = int.from_bytes(data_io.read(2), 'big')
                next_state = read_varint(data_io)

                if next_state == 1:
                    self.state = "STATUS"
                elif next_state == 2:
                    self.state = "LOGIN"
        elif self.state == "LOGIN":
            if direction == "Server -> Client" and packet.id == 0x01: # Encryption Request
                data_io = io.BytesIO(packet.data)
                server_id_len = read_varint(data_io)
                server_id = data_io.read(server_id_len).decode('utf-8')
                public_key_len = read_varint(data_io)
                public_key = data_io.read(public_key_len)
                verify_token_len = read_varint(data_io)
                verify_token = data_io.read(verify_token_len)

                shared_secret = get_random_bytes(16)

                server_hash = java_hex_digest(server_id.encode('ascii') + shared_secret + public_key)

                response = requests.post("https://sessionserver.mojang.com/session/minecraft/join", json={
                    "accessToken": self.args.token,
                    "selectedProfile": self.args.username,
                    "serverId": server_hash
                })

                if response.status_code != 204:
                    print(f"Error authenticating with Mojang: {response.text}")
                    return

                rsa_key = RSA.import_key(public_key)
                cipher = PKCS1_OAEP.new(rsa_key)

                encrypted_secret = cipher.encrypt(shared_secret)
                encrypted_token = cipher.encrypt(verify_token)

                response_packet = Packet(0x01,
                    self.write_varint(len(encrypted_secret)) + encrypted_secret +
                    self.write_varint(len(encrypted_token)) + encrypted_token
                )

                self.send_packet(response_packet, self.remote_socket)

                self.client_cipher = AESCipher(shared_secret)
                self.server_cipher = AESCipher(shared_secret)
                return

            elif direction == "Server -> Client" and packet.id == 0x03: # Set Compression
                self.compression_threshold = read_varint(io.BytesIO(packet.data))
            elif direction == "Server -> Client" and packet.id == 0x02: # Login Success
                self.state = "GAME"
        elif self.state == "GAME":
            self.handle_game_packet(packet, direction)

        self.send_packet(packet, dest_socket)

    def handle_game_packet(self, packet, direction):
        if direction == "Server -> Client":
            if packet.id == 0x22: # Chunk Data
                if self.args.disable_chunk_saving:
                    return

                try:
                    data_io = io.BytesIO(packet.data)
                    chunk_x = int.from_bytes(data_io.read(4), 'big', signed=True)
                    chunk_z = int.from_bytes(data_io.read(4), 'big', signed=True)

                    heightmaps = nbtlib.load(data_io)

                    data_size = read_varint(data_io)

                    chunk_section_data = data_io.read()

                    output_dir = Path(self.args.output)
                    region_dir = output_dir / "region"
                    if not region_dir.exists():
                        region_dir.mkdir(parents=True)

                    region_x = chunk_x >> 5
                    region_z = chunk_z >> 5

                    region_file = RegionFile(region_dir / f"r.{region_x}.{region_z}.mca")

                    chunk = Chunk(chunk_section_data)

                    nbt_data = nbtlib.File({
                        'Level': nbtlib.Compound({
                            'xPos': nbtlib.Int(chunk_x),
                            'zPos': nbtlib.Int(chunk_z),
                            'Heightmaps': heightmaps.root[''],
                            'Sections': chunk.sections,
                        })
                    }, byteorder='big')

                    with io.BytesIO() as f:
                        nbt_data.write(f)
                        region_file.write_chunk(chunk_x, chunk_z, f.getvalue())

                    print(f"Saved chunk {chunk_x}, {chunk_z} to r.{region_x}.{region_z}.mca")

                except Exception as e:
                    print(f"Error parsing chunk data: {e}")

    def write_varint(self, value):
        result = b''
        while True:
            byte = value & 0b01111111
            value >>= 7
            if value != 0:
                byte |= 0b10000000
            result += byte.to_bytes(1, 'big')
            if value == 0:
                break
        return result

def start_proxy(args):
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind(("localhost", args.local_port))
        server_socket.listen(1)
        print(f"Proxy server listening on localhost:{args.local_port}")

        while True:
            client_socket, client_addr = server_socket.accept()
            print(f"Accepted connection from {client_addr}")
            remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote_socket.connect((args.server, 25565))

            connection = Connection(client_socket, remote_socket, args)

            client_thread = threading.Thread(target=connection.forward_data, args=(connection.client_socket, connection.remote_socket, "Client -> Server"))
            remote_thread = threading.Thread(target=connection.forward_data, args=(connection.remote_socket, connection.client_socket, "Server -> Client"))

            client_thread.start()
            remote_thread.start()

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        server_socket.close()

def main():
    parser = argparse.ArgumentParser(description="A Python script to download Minecraft worlds.")

    # Set hardcoded defaults here
    parser.add_argument("--server", "-s", help="The address of the remote server to connect to.")
    parser.add_argument("--token", "-t", help="Minecraft access token.")
    parser.add_argument("--username", "-u", help="Your Minecraft username.")
    parser.add_argument("--local-port", "-l", type=int, default=25565, help="The port on which the world downloader's server will run.")
    parser.add_argument("--output", "-o", default="world", help="The world output directory.")
    parser.add_argument("--disable-chunk-saving", action="store_true", default=False, help="Disable writing chunks to disk.")
    parser.add_argument("--clear-settings", action="store_true", default=False, help="Clear settings by deleting the config.json file, then exit.")

    config_path = Path("cache/config.json")

    # Load config from file to override hardcoded defaults
    config = {}
    if config_path.exists():
        with open(config_path, "r") as f:
            config = json.load(f)

    parser.set_defaults(**config)

    args = parser.parse_args()

    # The rest of the logic
    if args.clear_settings:
        if config_path.exists():
            config_path.unlink()
            print("Settings cleared.")
        sys.exit(0)

    # Save the final effective configuration
    if not config_path.parent.exists():
        config_path.parent.mkdir(parents=True)
    with open(config_path, "w") as f:
        # Don't save `clear_settings` to the config file
        final_config = vars(args).copy()
        final_config.pop('clear_settings', None)
        json.dump(final_config, f, indent=4)

    print("Configuration saved to cache/config.json")

    if hasattr(args, 'server') and args.server:
        start_proxy(args)
    else:
        print("Error: --server argument is required via command line or in cache/config.json.")
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
