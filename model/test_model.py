
import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

DATASET = "../all_usernames_results.csv"
MODEL_FILE = "engagement_model.pkl"

df = pd.read_csv(DATASET)

features = [
    "Followers",
    "Category",
    "Posting Frequency (per month)",
    "Hashtags"
]
target = "Engagement Rate (%)"

df = df[features + [target]].dropna()
df = df[df["Followers"] > 0]

X = df[features]
y = df[target]

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
    ("regressor", RandomForestRegressor(
        n_estimators=300,
        random_state=42,
        min_samples_leaf=2,
        n_jobs=-1
    ))
])

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

model.fit(X_train, y_train)
predictions = model.predict(X_test)

print("Training samples:", len(X_train))
print("Testing samples:", len(X_test))
print("MAE:", round(mean_absolute_error(y_test, predictions), 4))
print("R²:", round(r2_score(y_test, predictions), 4))

joblib.dump(model, MODEL_FILE)
print("Model saved to:", MODEL_FILE)
