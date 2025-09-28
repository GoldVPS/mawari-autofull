#!/usr/bin/env python3
import sys, time, requests, yaml
from pathlib import Path

CFG = yaml.safe_load(Path("config.yaml").read_text())
F = CFG.get("faucet", {})

def claim_once(address: str) -> bool:
    url = F.get("url"); method = (F.get("method","POST") or "POST").upper()
    field = F.get("address_field","address")
    headers = dict(F.get("extra_headers",{}) or {})
    payload = dict(F.get("extra_payload",{}) or {})
    payload[field] = address
    try:
        if method == "POST":
            r = requests.post(url, json=payload, headers=headers, timeout=20)
        else:
            r = requests.get(url, params=payload, headers=headers, timeout=20)
        print("Faucet resp:", r.status_code, (r.text or "")[:200])
        return r.ok
    except Exception as e:
        print("Faucet error:", e)
        return False

def claim_with_retries(address: str) -> bool:
    if not F.get("enabled", True):
        print("Faucet disabled in config.")
        return False
    retries = int(F.get("max_retries", 3))
    waitsec = int(F.get("wait_seconds", 6))
    for i in range(1, retries+1):
        print(f"[FAUCET] request {i}/{retries} → {address}")
        ok = claim_once(address)
        if ok:
            return True
        time.sleep(waitsec)
    return False

if __name__=="__main__":
    if len(sys.argv)<2:
        print("Usage: python3 faucet_claim.py <address>")
        sys.exit(1)
    ok = claim_with_retries(sys.argv[1])
    sys.exit(0 if ok else 2)
