#!/usr/bin/env python3
import json, time, re, subprocess, yaml
from pathlib import Path
from web3 import Web3
from eth_account import Account

# Directories for node cache
BASE_DIR = Path.home() / ".mawari_automation"
WORKER = "worker1"
WORKER_DIR = BASE_DIR / "workers" / WORKER
CACHE_DIR = WORKER_DIR / "cache"
META = WORKER_DIR / "meta.json"

def load_cfg():
    return yaml.safe_load(Path("config.yaml").read_text())

def ensure_dirs():
    for p in (WORKER_DIR, CACHE_DIR):
        p.mkdir(parents=True, exist_ok=True)

def derive_owner(cfg):
    if cfg.get("owner_address"):
        return cfg["owner_address"]
    return Account.from_key(cfg["owner_private_key"]).address

def run_container(image, owner_addr):
    print("== Run Guardian node ==")
    cname = f"mawari_{WORKER}"
    subprocess.run(["bash","-lc", f"docker rm -f {cname} >/dev/null 2>&1 || true"])
    cmd = ["docker","run","--pull","always","--name",cname,
           "-v", f"{str(CACHE_DIR)}:/app/cache",
           "-e", f"OWNERS_ALLOWLIST={owner_addr}",
           "--restart=unless-stopped","-d", image]
    print(" ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
    else:
        print(r.stdout.strip())

def capture_burner(timeout=60):
    print("== Capture burner address ==")
    cname = f"mawari_{WORKER}"
    p = subprocess.Popen(["docker","logs","-f","--tail=200",cname], stdout=subprocess.PIPE, text=True)
    burner = None; t0 = time.time()
    while time.time() - t0 < timeout:
        line = p.stdout.readline()
        if not line:
            time.sleep(0.1); continue
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
        print("Failed to capture burner in logs.")
    return burner

def load_abi(name):
    return json.loads(Path(f"abi/{name}.json").read_text())["abi"]

def get_balance_native(w3, addr):
    return float(w3.from_wei(w3.eth.get_balance(w3.to_checksum_address(addr)), "ether"))

def wait_for_balance(w3, addr, min_need, tries=10, sleep=6):
    min_need = float(min_need)
    for _ in range(tries):
        bal = get_balance_native(w3, addr)
        print(f"[BAL] {addr} = {bal:.6f} MAWARI (need >= {min_need})")
        if bal >= min_need:
            return True
        time.sleep(sleep)
    return False

def transfer_native_v7(w3, sender_pk, to_addr, amount_native, chain_id):
    sender_addr = Account.from_key(sender_pk).address
    tx = {
        "to": w3.to_checksum_address(to_addr),
        "value": int(float(amount_native) * (10**18)),
        "gas": 21000,
        "gasPrice": w3.eth.gas_price,
        "nonce": w3.eth.get_transaction_count(sender_addr),
        "chainId": int(chain_id),
    }
    signed = w3.eth.account.sign_transaction(tx, private_key=sender_pk)
    txh = w3.eth.send_raw_transaction(signed.raw_transaction)  # Web3.py v7
    return w3.to_hex(txh)

def discover_token_ids(cfg, owner_addr):
    """Cari tokenId dari event Transfer (to == owner). Verifikasi ownerOf."""
    w3 = Web3(Web3.HTTPProvider(cfg["rpc_url"]))
    nft = w3.eth.contract(address=w3.to_checksum_address(cfg["nft_contract"]), abi=load_abi("NFT"))

    latest = w3.eth.block_number
    window = int((cfg.get("discovery") or {}).get("window_blocks", 50000))
    from_block = max(0, latest - window)

    print(f"== Discover tokenIds via events: blocks {from_block}..{latest}")
    # ambil log Transfer(to=owner)
    try:
        logs = nft.events.Transfer().get_logs(
            fromBlock=from_block,
            toBlock=latest,
            argument_filters={"to": w3.to_checksum_address(owner_addr)},
        )
    except Exception as e:
        print("get_logs error:", repr(e))
        logs = []

    token_ids = []
    for ev in logs:
        try:
            tid = int(ev["args"]["tokenId"])
            token_ids.append(tid)
        except Exception:
            continue

    # dedup & verifikasi ownerOf == owner
    token_ids = sorted(set(token_ids))
    confirmed = []
    for tid in token_ids:
        try:
            current_owner = nft.functions.ownerOf(tid).call()
            if current_owner.lower() == owner_addr.lower():
                confirmed.append(tid)
        except Exception:
            continue

    print(f"Discovered tokenIds (owned by {owner_addr}):", confirmed)
    return confirmed

def approve_and_delegate(cfg, token_ids, burner):
    w3 = Web3(Web3.HTTPProvider(cfg["rpc_url"]))
    chain = int(cfg["chain_id"])
    owner_pk = cfg["owner_private_key"]
    owner_addr = Account.from_key(owner_pk).address
    nft = w3.eth.contract(address=w3.to_checksum_address(cfg["nft_contract"]), abi=load_abi("NFT"))
    hub = w3.eth.contract(address=w3.to_checksum_address(cfg["delegation_hub"]), abi=load_abi("DelegationHub"))

    nonce = w3.eth.get_transaction_count(owner_addr)
    for tid in token_ids:
        # approve
        txa = nft.functions.approve(w3.to_checksum_address(cfg["delegation_hub"]), int(tid)).build_transaction({
            "chainId": chain, "nonce": nonce,
            "gas": 250000, "gasPrice": w3.eth.gas_price
        })
        sa = w3.eth.account.sign_transaction(txa, private_key=owner_pk)
        ha = w3.eth.send_raw_transaction(sa.raw_transaction)
        print("Approve tx:", w3.to_hex(ha))
        nonce += 1

        # delegate
        txd = hub.functions.delegate(int(tid), w3.to_checksum_address(burner)).build_transaction({
            "chainId": chain, "nonce": nonce,
            "gas": 600000, "gasPrice": w3.eth.gas_price
        })
        sd = w3.eth.account.sign_transaction(txd, private_key=owner_pk)
        hd = w3.eth.send_raw_transaction(sd.raw_transaction)
        print("Delegate tx:", w3.to_hex(hd))
        nonce += 1

def main():
    cfg = load_cfg()
    ensure_dirs()
    owner_addr = derive_owner(cfg)
    print("Owner:", owner_addr)

    # 1) start node & ambil burner
    run_container(cfg["docker_image"], owner_addr)
    burner = capture_burner()
    if not burner:
        print("Gagal mendapatkan burner dari log.")
        return

    # 2) fund burner dari owner jika kurang
    w3 = Web3(Web3.HTTPProvider(cfg["rpc_url"]))
    min_bal = cfg.get("min_burner_balance", "0.5")
    if not wait_for_balance(w3, burner, min_bal, tries=1, sleep=1):
        amt = cfg.get("fund_burner_amount", "1")
        print(f"Funding burner {burner} from owner ({amt} MAWARI)")
        txh = transfer_native_v7(w3, cfg["owner_private_key"], burner, amt, cfg["chain_id"])
        print("Fund tx:", txh)
        wait_for_balance(w3, burner, min_bal, tries=10, sleep=6)

    # 3) ambil tokenIds: auto-discover jika diaktifkan, kalau tidak pakai dari config
    token_ids = []
    if cfg.get("auto_discover_token_ids", True):
        token_ids = discover_token_ids(cfg, owner_addr)
    if not token_ids:
        token_ids = cfg.get("token_ids") or []
        print("Using token_ids from config:", token_ids)

    if not token_ids:
        print("Tidak ada tokenId ditemukan/diisi; berhenti.")
        return

    # 4) approve + delegate
    approve_and_delegate(cfg, token_ids, burner)

    print("Done. Cek: docker logs -f --tail=200 mawari_worker1")

if __name__ == "__main__":
    main()
