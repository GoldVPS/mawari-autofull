#!/usr/bin/env python3
import os, sys, json, yaml, time
from pathlib import Path
from web3 import Web3
from eth_account import Account

def load_cfg():
    return yaml.safe_load(Path("config.yaml").read_text())

def load_abi():
    return json.loads(Path("abi/NFT.json").read_text())["abi"]

def main():
    cfg = load_cfg()
    rpc = cfg["rpc_url"]; chain_id = int(cfg["chain_id"])
    nft_addr = cfg["nft_contract"]
    count = int(cfg["mint"]["count"])
    func = cfg["mint"]["function"]
    price = float(cfg["mint"].get("price_native_per_nft","0"))
    pk = cfg["owner_private_key"]
    if not (rpc and nft_addr and pk):
        print("Missing rpc/nft_contract/owner_private_key")
        sys.exit(2)

    w3 = Web3(Web3.HTTPProvider(rpc))
    acct = Account.from_key(pk)
    nft = w3.eth.contract(address=w3.to_checksum_address(nft_addr), abi=load_abi())

    total_value = int(price * (10**18)) * count
    tx = getattr(nft.functions, func)(count).build_transaction({
        "chainId": chain_id,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "gas": 1_500_000,
        "gasPrice": w3.eth.gas_price,
        "value": total_value
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=pk)
    txh = w3.eth.send_raw_transaction(signed.rawTransaction)
    h = w3.to_hex(txh)
    print("Mint tx:", h)
    print("Waiting for receipt...")
    rec = w3.eth.wait_for_transaction_receipt(h, timeout=240)

    # parse ERC721 Transfer to collect tokenIds
    token_ids = []
    try:
        ev_transfer = nft.events.Transfer()
        for log in rec["logs"]:
            try:
                ev = ev_transfer.process_log(log)
                if ev["args"]["to"].lower() == acct.address.lower():
                    token_ids.append(int(ev["args"]["tokenId"]))
            except Exception:
                continue
    except Exception:
        pass

    if token_ids:
        Path("minted_ids.json").write_text(json.dumps(token_ids, indent=2))
        print("Minted tokenIds:", token_ids)
    else:
        print("No tokenIds parsed; provide them manually later.")
    time.sleep(3)

if __name__=="__main__":
    main()
