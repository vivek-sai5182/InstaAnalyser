
import pandas as pd
import joblib

DATASET = "../all_usernames_results.csv"
ENGAGEMENT_MODEL = "engagement_model.pkl"
AUTOMATION_MODEL = "automation_model.pkl"
OUTPUT = "ranked_influencers.csv"

df = pd.read_csv(DATASET)

engagement_model = joblib.load(ENGAGEMENT_MODEL)
automation_model = joblib.load(AUTOMATION_MODEL)

features = [
    "Followers",
    "Category",
    "Posting Frequency (per month)",
    "Hashtags"
]
df = pd.read_csv(DATASET)

df["Followers"] = pd.to_numeric(df["Followers"], errors="coerce")
df["Posting Frequency (per month)"] = pd.to_numeric(
    df["Posting Frequency (per month)"], errors="coerce"
)

df["Category"] = df["Category"].fillna("unknown")
df["Hashtags"] = df["Hashtags"].fillna("")
df = df.dropna(subset=["Followers", "Posting Frequency (per month)"])
df["Predicted Engagement (%)"] = engagement_model.predict(df[features])
df["Automation Proxy Score (%)"] = (
    automation_model.predict_proba(df[features])[:, 1] * 100
).round(2)

# Normalize metrics to a 0–100 scale for ranking.
engagement = df["Predicted Engagement (%)"].clip(lower=0)
frequency = df["Posting Frequency (per month)"].clip(lower=0)
followers = df["Followers"].clip(lower=0)

def normalize(series):
    maximum = series.max()
    if maximum == 0:
        return series * 0
    return series / maximum * 100

df["Engagement Score"] = normalize(engagement)
df["Posting Frequency Score"] = normalize(frequency)
df["Follower Score"] = normalize(followers)

# Engagement gets the highest weight.
df["Influencer Score"] = (
    df["Engagement Score"] * 0.60
    + df["Posting Frequency Score"] * 0.25
    + df["Follower Score"] * 0.15
).round(2)

df = df.sort_values("Influencer Score", ascending=False)
df.insert(0, "Rank", range(1, len(df) + 1))

df.to_csv(OUTPUT, index=False, encoding="utf-8-sig")

print("Total influencers ranked:", len(df))
print("\nTop 10 influencers:")
print(df[[
    "Rank",
    "Name",
    "Followers",
    "Category",
    "Predicted Engagement (%)",
    "Posting Frequency (per month)",
    "Influencer Score"
]].head(10).to_string(index=False))

print("\nSaved to:", OUTPUT)
