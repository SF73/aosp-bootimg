from dataclasses import dataclass
import struct

@dataclass
class LocalFileHeader:
    FIXED_SIZE = 30  # Fixed size of the local file header (excluding variable fields)
    
    signature: bytes
    version_needed_to_extract: int
    general_purpose_bit_flag: int
    compression_method: int
    last_mod_time: int
    last_mod_date: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    file_name_length: int
    extra_field_length: int
    file_name: str
    extra_field: bytes

    @classmethod
    def unpack(cls, data: bytes, file_name: str, extra_field: bytes):
        header_struct = struct.unpack("<4s5H3I2H", data[:cls.FIXED_SIZE])
        return cls(
            signature=header_struct[0],
            version_needed_to_extract=header_struct[1],
            general_purpose_bit_flag=header_struct[2],
            compression_method=header_struct[3],
            last_mod_time=header_struct[4],
            last_mod_date=header_struct[5],
            crc32=header_struct[6],
            compressed_size=header_struct[7],
            uncompressed_size=header_struct[8],
            file_name_length=header_struct[9],
            extra_field_length=header_struct[10],
            file_name=file_name,
            extra_field=extra_field
        )


@dataclass
class CentralDirectoryFileHeader:
    FIXED_SIZE = 46  # Fixed size of the central directory file header (excluding variable fields)
    
    signature: bytes
    version_made_by: int
    version_needed_to_extract: int
    general_purpose_bit_flag: int
    compression_method: int
    last_mod_time: int
    last_mod_date: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    file_name_length: int
    extra_field_length: int
    file_comment_length: int
    disk_number_start: int
    internal_file_attributes: int
    external_file_attributes: int
    offset: int
    file_name: str
    extra_field: bytes
    file_comment: str

    @classmethod
    def unpack(cls, data: bytes, file_name: str, extra_field: bytes, file_comment: str):
        header_struct = struct.unpack("<4s6H3I5H2I", data[:cls.FIXED_SIZE])
        return cls(
            signature=header_struct[0],
            version_made_by=header_struct[1],
            version_needed_to_extract=header_struct[2],
            general_purpose_bit_flag=header_struct[3],
            compression_method=header_struct[4],
            last_mod_time=header_struct[5],
            last_mod_date=header_struct[6],
            crc32=header_struct[7],
            compressed_size=header_struct[8],
            uncompressed_size=header_struct[9],
            file_name_length=header_struct[10],
            extra_field_length=header_struct[11],
            file_comment_length=header_struct[12],
            disk_number_start=header_struct[13],
            internal_file_attributes=header_struct[14],
            external_file_attributes=header_struct[15],
            offset=header_struct[16],
            file_name=file_name,
            extra_field=extra_field,
            file_comment=file_comment
        )
    