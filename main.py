import argparse
import binascii
from pathlib import Path
import struct
import zlib
import requests
import re

from zipHeaders import LocalFileHeader, CentralDirectoryFileHeader

INNER_ZIP_PATTERN = re.compile(r".*image.*\.zip", re.IGNORECASE)


class RemoteFileFetcher:
    def __init__(self):
        self.session = requests.Session()

    def fetch_last_n_bytes(self, url, n_bytes):
        response = self.session.head(url)
        if response.status_code == 200 and "Content-Length" in response.headers:
            content_length = int(response.headers["Content-Length"])
            start_byte = max(0, content_length - n_bytes)
            headers = {"Range": f"bytes={start_byte}-{content_length - 1}"}
            response = self.session.get(url, headers=headers)
            if response.status_code == 206:  # Partial content
                return response.content, content_length
            else:
                raise Exception(
                    f"Failed to fetch the last {n_bytes} bytes. Status code: {response.status_code}"
                )
        else:
            raise Exception(
                f"Failed to retrieve content length. Status code: {response.status_code}"
            )

    def fetch_range(self, url, start_byte, end_byte):
        headers = {"Range": f"bytes={start_byte}-{end_byte}"}
        response = self.session.get(url, headers=headers)
        if response.status_code == 206:  # Partial content
            return response.content
        else:
            raise Exception(
                f"Failed to fetch byte range. Status code: {response.status_code}"
            )


class ZipCentralDirectoryParser:
    EOCD_SIGNATURE = b"\x50\x4b\x05\x06"  # End of central directory signature
    EOCD_SIZE = 22  # Fixed size for EOCD
    CENTRAL_DIRECTORY_HEADER_SIGNATURE = (
        b"\x50\x4b\x01\x02"  # Central directory file header signature
    )

    def __init__(self):
        pass

    def find_eocd(self, data):
        eocd_offset = data.rfind(self.EOCD_SIGNATURE)
        if eocd_offset == -1:
            raise Exception("EOCD signature not found.")
        return eocd_offset

    def parse_eocd(self, eocd_data):
        if len(eocd_data) < self.EOCD_SIZE:
            raise Exception("EOCD record is incomplete or corrupted.")
        eocd_struct = struct.unpack("<4sHHHHIIH", eocd_data[: self.EOCD_SIZE])
        eocd_signature = eocd_struct[0]
        if eocd_signature != self.EOCD_SIGNATURE:
            raise Exception("EOCD signature mismatch.")
        return {
            "total_entries": eocd_struct[3],
            "central_directory_size": eocd_struct[5],
            "central_directory_offset": eocd_struct[6],
        }

    def parse_central_directory(self, central_directory_data):
        entries = []
        offset = 0
        while offset < len(central_directory_data):
            signature = central_directory_data[offset : offset + 4]
            if signature != self.CENTRAL_DIRECTORY_HEADER_SIGNATURE:
                raise Exception(
                    f"Invalid central directory file header signature : {signature}"
                )

            # Unpack using the CentralDirectoryFileHeader dataclass
            header_data = central_directory_data[
                offset : offset + CentralDirectoryFileHeader.FIXED_SIZE
            ]
            # Step 1: Unpack the fixed-size portion
            fixed_header_data = central_directory_data[
                offset : offset + CentralDirectoryFileHeader.FIXED_SIZE
            ]
            central_directory_entry = CentralDirectoryFileHeader.unpack(
                fixed_header_data, file_name="", extra_field=b"", file_comment=""
            )

            central_directory_entry.file_name = central_directory_data[
                offset
                + CentralDirectoryFileHeader.FIXED_SIZE : offset
                + CentralDirectoryFileHeader.FIXED_SIZE
                + central_directory_entry.file_name_length
            ].decode("utf-8")

            central_directory_entry.extra_field = central_directory_data[
                offset
                + CentralDirectoryFileHeader.FIXED_SIZE
                + central_directory_entry.file_name_length : offset
                + CentralDirectoryFileHeader.FIXED_SIZE
                + central_directory_entry.file_name_length
                + central_directory_entry.extra_field_length
            ]

            central_directory_entry.file_comment = central_directory_data[
                offset
                + CentralDirectoryFileHeader.FIXED_SIZE
                + central_directory_entry.file_name_length
                + central_directory_entry.extra_field_length : offset
                + CentralDirectoryFileHeader.FIXED_SIZE
                + central_directory_entry.file_name_length
                + central_directory_entry.extra_field_length
                + central_directory_entry.file_comment_length
            ].decode("utf-8")

            offset += (
                CentralDirectoryFileHeader.FIXED_SIZE
                + central_directory_entry.file_name_length
                + central_directory_entry.extra_field_length
                + central_directory_entry.file_comment_length
            )

            entries.append(central_directory_entry)

        return entries


def main(url):

    fetcher = RemoteFileFetcher()
    parser = ZipCentralDirectoryParser()

    try:
        # Fetch the last 64 KB to locate the EOCD
        last_bytes, content_length = fetcher.fetch_last_n_bytes(url, 65536)

        # Find the EOCD in the last 64KB of data
        eocd_offset = parser.find_eocd(last_bytes)
        eocd_data = last_bytes[eocd_offset : eocd_offset + parser.EOCD_SIZE]

        # Parse the EOCD to get the central directory's offset and size
        eocd_info = parser.parse_eocd(eocd_data)
        central_directory_offset = eocd_info["central_directory_offset"]
        central_directory_size = eocd_info["central_directory_size"]

        # Fetch the central directory based on the parsed EOCD information
        central_directory_data = fetcher.fetch_range(
            url,
            central_directory_offset,
            central_directory_offset + central_directory_size - 1,
        )

        # Parse the central directory entries
        entries = parser.parse_central_directory(central_directory_data)

        image_zip = None
        for entry in entries:
            if INNER_ZIP_PATTERN.match(entry.file_name):
                image_zip = entry
                print(f"Image ZIP found: {image_zip.file_name} at offset {image_zip.offset}")
                break
        else:
            raise FileNotFoundError(
                f"No image zip found matching {str(INNER_ZIP_PATTERN)}"
            )

        # Fetch the local file header (typically the first 30 bytes)
        local_file_header_data = fetcher.fetch_range(
            url, image_zip.offset, image_zip.offset + 30 - 1
        )

        image_file_header = LocalFileHeader.unpack(local_file_header_data, "", b"")

        # Calculate the total size of the local file header
        local_file_header_size = (
            LocalFileHeader.FIXED_SIZE
            + image_file_header.extra_field_length
            + image_file_header.file_name_length
        )

        assert image_zip.compressed_size == image_file_header.compressed_size

        end_of_image_zip = (
            image_zip.offset + local_file_header_size + image_zip.compressed_size
        )

        image_zip_last_bytes = fetcher.fetch_range(
            url, end_of_image_zip - 4096, end_of_image_zip - 1
        )
        
        # Find EOCD in the image zip
        image_zip_eocd_offset = parser.find_eocd(image_zip_last_bytes)

        # Parse the EOCD to get the central directory's offset and size
        eocd_data = image_zip_last_bytes[
            image_zip_eocd_offset : image_zip_eocd_offset + parser.EOCD_SIZE
        ]
        eocd_info = parser.parse_eocd(eocd_data)
        central_directory_offset = eocd_info["central_directory_offset"]
        central_directory_size = eocd_info["central_directory_size"]

        print(f"Central Directory found in image zip\n{eocd_info}")
        
        # The central directory offset is relative to the beginning of the image ZIP, so adjust by adding image_zip.offset
        absolute_central_directory_offset = (
            image_zip.offset + central_directory_offset + local_file_header_size
        )

        # Fetch the central directory data
        central_directory_data = fetcher.fetch_range(
            url,
            absolute_central_directory_offset,
            absolute_central_directory_offset + central_directory_size - 1,
        )

        # Parse the central directory of the image zip
        nested_entries = parser.parse_central_directory(central_directory_data)

        # List all files in the nested zip central directory
        boot_img = None
        for nested_entry in nested_entries:
            if nested_entry.file_name == "boot.img":
                boot_img = nested_entry
                print(f"{boot_img.file_name} found {boot_img.crc32=:x}, {boot_img.compressed_size=}, {boot_img.uncompressed_size=}")
                break
        else:
            raise FileNotFoundError("Boot image not found in nested zip")
        
        # Offset in the outer zip =
        boot_data_start = (
            image_zip.offset # Postion of the Image zip
            + local_file_header_size # localfile header size of the image zip
            + boot_img.offset # offset of the boot.img from the image zip
            + LocalFileHeader.FIXED_SIZE # local file header of the boot_image
            + boot_img.file_name_length
            + boot_img.extra_field_length
        )
        boot_data_stop = boot_data_start + boot_img.compressed_size
        compressed_data = fetcher.fetch_range(url, boot_data_start, boot_data_stop)
        if boot_img.compression_method == 0:  # No compression
            assert(boot_img.compressed_size == boot_img.uncompressed_size)
            decompressed_data = compressed_data
        elif boot_img.compression_method == 8:  # Deflate compression
            decompressed_data = zlib.decompress(compressed_data, wbits=-zlib.MAX_WBITS)
        else:
            raise NotImplementedError(f"Unsupported compression method: {boot_img.compression_method}")
            
        computed_crc32 = binascii.crc32(decompressed_data) & 0xFFFFFFFF
        if computed_crc32 != boot_img.crc32:
            raise ValueError(f"Computed CRC32 ({computed_crc32}) doesn't match retrieved one {boot_img.crc32}")
        

        path = Path(image_zip.file_name).parent / boot_img.file_name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(decompressed_data)

        # # Apply file permissions
        # apply_file_permissions(entry.file_name, entry.external_file_attributes)

        # # Apply modification time from the ZIP file's MS-DOS date and time fields
        # apply_modification_time(entry.file_name, entry.last_mod_date, entry.last_mod_time)
        # print(f"{boot_img.file_name} saved !")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Download and process ZIP files from a given URL.")
    parser.add_argument("url", type=str, help="The URL of the ZIP file to process.")
    args = parser.parse_args()

    url = args.url  # Get the URL from the command-line argument
    main(url)
