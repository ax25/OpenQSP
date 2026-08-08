#!/usr/bin/env python3
"""Decode an OpenQSP Core frame represented as hexadecimal bytes."""
import argparse
from dataclasses import asdict
from openqsp.protocol import decode_frame_with_flags

def main():
 p=argparse.ArgumentParser();p.add_argument('hex');a=p.parse_args()
 obj,flags=decode_frame_with_flags(bytes.fromhex(a.hex))
 print(type(obj).__name__);print(f'flags: 0x{flags:02x}')
 for key,value in asdict(obj).items(): print(f'{key}: {value}')
if __name__=='__main__':main()
