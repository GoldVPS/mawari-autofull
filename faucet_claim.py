#!/usr/bin/env python3
import sys, yaml, requests
from pathlib import Path

CFG = yaml.safe_load(Path("config.yaml").read_text())
f = CFG.get("faucet",{})

def main(addr):
    if not f.get("enabled", False):
        print("Faucet disabled. (Enable in config.yaml if you have API endpoint)")
        return 0
    url = f.get("url"); method = f.get("method","POST").upper()
    field = f.get("address_field","address")
    payload = dict(f.get("extra_payload",{})); payload[field]=addr
    headers = dict(f.get("extra_headers",{}))
    try:
        if method=="POST":
            r = requests.post(url, json=payload, headers=headers, timeout=20)
        else:
            r = requests.get(url, params=payload, headers=headers, timeout=20)
        print("Faucet resp:", r.status_code, r.text[:300])
        return 0 if r.ok else 2
    except Exception as e:
        print("Faucet error:", e)
        return 2

if __name__=="__main__":
    if len(sys.argv)<2:
        print("Usage: python3 faucet_claim.py <address>")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
