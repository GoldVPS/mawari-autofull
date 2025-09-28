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

def get_owner_addr(cfg):
    if cfg.get("owner_address"):
        return cfg["owner_address"]
    return Account.from_key(cfg["owner_private_key"]).address

def get_balance_native(w3, addr):
    return w3.from_wei(w3.eth.get_balance(w3.to_checksum_address(addr)), "ether")

def wait_balance(w3, addr, min_need, tries=15, sleep=6):
    min_need = float(min_need)
    for i in range(tries):
        bal = float(get_balance_native(w3, addr))
        print(f"[BAL] {addr} = {bal:.6f} MAWARI (need >= {min_need})")
        if bal >= min_need:
            return True
        time.sleep(sleep)
    return False

def faucet_claim(addr):
    print(f"== Faucet claim for {addr} ==")
    r = subprocess.run(["bash","-lc", f". .venv/bin/activate 2>/dev/null || true; python3 faucet_claim.py {addr}"], capture_output=True, text=True)
    print(r.stdout + r.stderr)
    return (r.returncode == 0)

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
    while time.time()-t0 < 45:
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
        print("Failed to capture burner in 45s; check logs manually.")
    return burner

def load_abi(name):
    return json.loads(Path(f"abi/{name}.json").read_text())["abi"]

def approve_delegate(cfg, token_ids, burner):
    w3 = Web3(Web3.HTTPProvider(cfg["rpc_url"]))
    chain = int(cfg["chain_id"])
    owner_pk = cfg["owner_private_key"]
    owner_addr = Account.from_key(owner_pk).address
    nft = w3.eth.contract(address=w3.to_checksum_address(cfg["nft_contract"]), abi=load_abi("NFT"))
    hub = w3.eth.contract(address=w3.to_checksum_address(cfg["delegation_hub"]), abi=load_abi("DelegationHub"))

    for tid in token_ids:
        # approve
        txa = nft.functions.approve(w3.to_checksum_address(cfg["delegation_hub"]), int(tid)).build_transaction({
            "chainId": chain, "nonce": w3.eth.get_transaction_count(owner_addr),
            "gas": 250000, "gasPrice": w3.eth.gas_price
        })
        sa = w3.eth.account.sign_transaction(txa, private_key=owner_pk)
        ha = w3.eth.send_raw_transaction(sa.rawTransaction); print("Approve tx:", w3.to_hex(ha))

        # delegate
        txd = hub.functions.delegate(int(tid), w3.to_checksum_address(burner)).build_transaction({
            "chainId": chain, "nonce": w3.eth.get_transaction_count(owner_addr),
            "gas": 600000, "gasPrice": w3.eth.gas_price
        })
        sd = w3.eth.account.sign_transaction(txd, private_key=owner_pk)
        hd = w3.eth.send_raw_transaction(sd.rawTransaction); print("Delegate tx:", w3.to_hex(hd))

def transfer_native(w3, pk, to_addr, amount, chain_id):
    sender = Account.from_key(pk).address
    value = int(float(amount) * (10**18))
    tx = {
        "to": w3.to_checksum_address(to_addr),
        "value": value,
        "gas": 21000,
        "gasPrice": w3.eth.gas_price,
        "nonce": w3.eth.get_transaction_count(sender),
        "chainId": int(chain_id)
    }
    signed = w3.eth.account.sign_transaction(tx, private_key=pk)
    txh = w3.eth.send_raw_transaction(signed.rawTransaction)
    return w3.to_hex(txh)

def main():
    cfg = load_cfg()
    ensure_dirs()
    owner = get_owner_addr(cfg)
    print("Owner:", owner)

    w3 = Web3(Web3.HTTPProvider(cfg["rpc_url"]))

    # 1) Faucet → OWNER until balance >= mint_total + gas buffer
    mint_total = float(cfg["mint"]["price_native_per_nft"]) * float(cfg["mint"]["count"])
    gas_buf = float(cfg["mint"].get("gas_buffer_native","0.05"))
    need_owner = mint_total + gas_buf
    if not wait_balance(w3, owner, need_owner, tries=1, sleep=1):  # quick check
        faucet_claim(owner)
        wait_balance(w3, owner, need_owner, tries=15, sleep=int(cfg["faucet"].get("wait_seconds",6)))

    # 2) MINT (simpan minted_ids.json)
    print("== Mint NFTs ==")
    r = subprocess.run(["bash","-lc", f". .venv/bin/activate 2>/dev/null || true; python3 mint_nft.py"], capture_output=True, text=True)
    print(r.stdout + r.stderr)

    # 3) RUN NODE & capture burner
    run_container(cfg, owner)
    burner = capture_burner()
    if not burner:
        return

    # 4) Faucet → BURNER sampai >= burner_min_native (fallback: transfer dari owner jika diizinkan)
    burner_min = float(cfg.get("burner_min_native","0.5"))
    if not wait_balance(w3, burner, burner_min, tries=1, sleep=1):
        faucet_ok = faucet_claim(burner)
        if faucet_ok:
            wait_balance(w3, burner, burner_min, tries=15, sleep=int(cfg["faucet"].get("wait_seconds",6)))
        if float(get_balance_native(w3, burner)) < burner_min and cfg.get("owner_fallback_transfer", True):
            print("Faucet to burner insufficient → fallback transfer from owner")
            txh = transfer_native(w3, cfg["owner_private_key"], burner, cfg.get("owner_fallback_amount","1"), cfg["chain_id"])
            print("Fallback transfer tx:", txh)

    # 5) APPROVE + DELEGATE (pakai minted_ids.json)
    mids = Path("minted_ids.json")
    token_ids = json.loads(mids.read_text()) if mids.exists() else []
    if not token_ids:
        print("No minted_ids.json; cannot delegate automatically.")
        return
    approve_delegate(cfg, token_ids, burner)

    print("Done. Check: docker logs -f --tail=200 mawari_worker1")

if __name__=="__main__":
    try:
        main()
    except Exception as e:
        print("ORCH error:", repr(e))
        raise
