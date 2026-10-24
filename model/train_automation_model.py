
import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report

DATASET = "../all_usernames_results.csv"
MODEL_FILE = "automation_model.pkl"

df = pd.read_csv(DATASET)

required = [
    "Followers",
    "Category",
    "Posting Frequency (per month)",
    "Hashtags"
]

df = df.dropna(subset=required).copy()
df = df[df["Followers"] > 0]

# Proxy labels: profiles with high posting frequency and
# high follower counts are labeled as likely automation users.
# These labels are assumptions, not verified automation usage.
follower_threshold = df["Followers"].median()
frequency_threshold = df["Posting Frequency (per month)"].median()

df["Automation Proxy"] = (
    (df["Followers"] >= follower_threshold)
    & (df["Posting Frequency (per month)"] >= frequency_threshold)
).astype(int)

X = df[required]
y = df["Automation Proxy"]

preprocessor = ColumnTransformer([
    ("category", OneHotEncoder(handle_unknown="ignore"), ["Category"]),
    ("numeric", StandardScaler(), [
        "Followers",
        "Posting Frequency (per month)"
    ]),
    ("hashtags", TfidfVectorizer(), "Hashtags")
])

model = Pipeline([
    ("preprocessor", preprocessor),
    ("classifier", RandomForestClassifier(
        n_estimators=200,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1
    ))
])

X_train, X_test, y_train, y_test = train_test_split(
    X, y,
    test_size=0.2,
    random_state=42,
    stratify=y
)

model.fit(X_train, y_train)
predictions = model.predict(X_test)

print("Training samples:", len(X_train))
print("Testing samples:", len(X_test))
print("Accuracy:", round(accuracy_score(y_test, predictions), 4))
print("\nClassification report:")
print(classification_report(
    y_test,
    predictions,
    target_names=["Lower proxy score", "Higher proxy score"]
))

joblib.dump(model, MODEL_FILE)
print("Model saved to:", MODEL_FILE)
