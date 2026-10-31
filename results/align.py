import pandas as pd

INPUT_FILE = "results/all_usernames_results.csv"
OUTPUT_FILE = "results/all_usernames_results.csv"

df = pd.read_csv(INPUT_FILE)

if "Username" not in df.columns:
    raise ValueError("Username column not found!")

df["Profile URL"] = (
    "www.instagram.com/"
    + df["Username"].astype(str).str.strip().str.lstrip("@")
    + "/"
)

df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

print(f"Added Profile URL for {len(df)} profiles.")