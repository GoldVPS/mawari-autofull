#!/usr/bin/env python3
import os, json, time, re, subprocess, yaml
from pathlib import Path
from web3 import Web3
from eth_account import Account

BASE_DIR = Path.home() / ".mawari_automation"
WORKERS_DIR = BASE_DIR / "workers"
WORKER = "worker1"
WORKER_DIR = WORKERS_DIR / WORKER
CACHE_DIR = WORKER_DIR / "cache"
META = WORKER_DIR / "meta.json"

def load_cfg():
    return yaml.safe_load(Path("config.yaml").read_text())

def ensure_dirs():
    for p in (WORKERS_DIR, WORKER_DIR, CACHE_DIR):
        p.mkdir(parents=True, exist_ok=True)

def derive_owner_address(cfg):
    if cfg.get("owner_address"):
        return cfg["owner_address"]
    return Account.from_key(cfg["owner_private_key"]).address

def faucet_claim(addr):
    cfg = load_cfg()
    if not cfg.get("faucet",{}).get("enabled", False):
        print("Faucet automation disabled. (Claim manually if needed.)")
        return
    print("== Faucet claim ==")
    r = subprocess.run(["python3","faucet_claim.py", addr], capture_output=True, text=True)
    print(r.stdout)

def mint_nft():
    print("== Mint NFTs ==")
    r = subprocess.run(["python3","mint_nft.py"], capture_output=True, text=True)
    print(r.stdout)

def run_container(cfg, owner):
    print("== Run Guardian node ==")
    img = cfg["docker_image"]
    cname = f"mawari_{WORKER}"
    subprocess.run(["bash","-lc", f"docker rm -f {cname} >/dev/null 2>&1 || true"])
    cmd = ["docker","run","--pull","always","--name",cname,
           "-v", f"{str(CACHE_DIR)}:/app/cache",
           "-e", f"OWNERS_ALLOWLIST={owner}",
           "--restart=unless-stopped","-d", img]
    print(" ".join(cmd))
    subprocess.run(cmd, check=False)

def capture_burner():
    print("== Capture burner address ==")
    cname = f"mawari_{WORKER}"
    p = subprocess.Popen(["docker","logs","-f","--tail=200",cname], stdout=subprocess.PIPE, text=True)
    burner = None; t0=time.time()
    while time.time()-t0 < 30:
        line = p.stdout.readline()
        if not line: time.sleep(0.1); continue
        print(line, end="")
        m = re.search(r'Using burner wallet.*\{"address":\s*"(0x[0-9a-fA-F]+)"}', line)
        if m:
            burner = m.group(1); break
    try: p.terminate()
    except: pass
    if burner:
        META.write_text(json.dumps({"burner": burner}, indent=2))
        print("Burner:", burner)
    else:
        print("Failed to capture burner in 30s; check logs manually.")
    return burner

def load_abi(name):
    return json.loads(Path(f"abi/{name}.json").read_text())["abi"]

def fund_native(w3, sender_pk, to_addr, amount_native_str, chain_id):
    sender = Account.from_key(sender_pk).address
    value = int(float(amount_native_str) * (10**18))
    tx = {
        "to": w3.to_checksum_address(to_addr),
        "value": value,
        "gas": 21000,
        "gasPrice": w3.eth.gas_price,
        "nonce": w3.eth.get_transaction_count(sender),
        "chainId": int(chain_id)
    }
    signed = w3.eth.account.sign_transaction(tx, private_key=sender_pk)
    txh = w3.eth.send_raw_transaction(signed.rawTransaction)
    return w3.to_hex(txh)

def fund_and_delegate(cfg, burner):
    print("== Fund burner & delegate ==")
    w3 = Web3(Web3.HTTPProvider(cfg["rpc_url"]))
    chain = int(cfg["chain_id"])
    nft = w3.eth.contract(address=w3.to_checksum_address(cfg["nft_contract"]), abi=load_abi("NFT"))
    hub = w3.eth.contract(address=w3.to_checksum_address(cfg["delegation_hub"]), abi=load_abi("DelegationHub"))
    fund_pk = cfg["fund_private_key"]
    owner_pk = cfg["owner_private_key"]

    # 1) FUND native
    txh = fund_native(w3, fund_pk or owner_pk, burner, cfg["fund_each"], chain)
    print("Fund native tx:", txh)

    # 2) Ambil tokenIds dari minted_ids.json
    token_ids = []
    mid = Path("minted_ids.json")
    if mid.exists():
        try:
            token_ids = json.loads(mid.read_text())
        except Exception:
            pass
    if not token_ids:
        print("No minted_ids.json found; provide tokenIds manually (comma separated):")
        tids = input().strip()
        token_ids = [int(t) for t in tids.split(",") if t.strip()]

    # approve + delegate
    owner_addr = Account.from_key(owner_pk).address
    for tid in token_ids:
        txa = nft.functions.approve(w3.to_checksum_address(cfg["delegation_hub"]), int(tid)).build_transaction({
            "chainId": chain, "nonce": w3.eth.get_transaction_count(owner_addr),
            "gas": 250000, "gasPrice": w3.eth.gas_price
        })
        sa = w3.eth.account.sign_transaction(txa, private_key=owner_pk)
        ha = w3.eth.send_raw_transaction(sa.rawTransaction); print("Approve tx:", w3.to_hex(ha))

        txd = hub.functions.delegate(int(tid), w3.to_checksum_address(burner)).build_transaction({
            "chainId": chain, "nonce": w3.eth.get_transaction_count(owner_addr),
            "gas": 600000, "gasPrice": w3.eth.gas_price
        })
        sd = w3.eth.account.sign_transaction(txd, private_key=owner_pk)
        hd = w3.eth.send_raw_transaction(sd.rawTransaction); print("Delegate tx:", w3.to_hex(hd))
    print("Done. Watch docker logs for 'accepted delegation offer'.")

def main():
    cfg = load_cfg()
    owner = derive_owner_address(cfg)
    ensure_dirs()
    print("Owner:", owner)
    faucet_claim(owner)  # no-op by default
    mint_nft()
    run_container(cfg, owner)
    burner = capture_burner()
    if not burner: return
    fund_and_delegate(cfg, burner)

if __name__=="__main__":
    main()
