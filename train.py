# OCCUPADO AI - Train the cancellation prediction model
import pandas as pd
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import pickle

print("Loading hotel booking data...")
df = pd.read_csv("hotel_bookings.csv")

print(f"Loaded {len(df):,} bookings")

features = [
    "lead_time",
    "arrival_date_week_number",
    "stays_in_weekend_nights",
    "stays_in_week_nights",
    "adults",
    "is_repeated_guest",
    "previous_cancellations",
    "previous_bookings_not_canceled",
    "booking_changes",
    "days_in_waiting_list",
    "adr",
    "total_of_special_requests"
]

target = "is_canceled"

df = df[features + [target]].dropna()

X = df[features]
y = df[target]

print("Splitting data into training and testing sets...")
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)
print(f"Training on {len(X_train):,} bookings")
print(f"Testing on {len(X_test):,} bookings")

print("Training Occupado AI...")
model = XGBClassifier(n_estimators=100, random_state=42, eval_metric="logloss")
model.fit(X_train, y_train)

predictions = model.predict(X_test)
accuracy = accuracy_score(y_test, predictions) * 100
print(f"Accuracy: {accuracy:.1f}%")

with open("occupado_model.pkl", "wb") as f:
    pickle.dump(model, f)

print("Model saved as occupado_model.pkl")
print("Occupado AI is ready!")