# OCCUPADO AI - Predict cancellation risk for a new booking
import pickle
import pandas as pd

# Load the trained AI model
with open("occupado_model.pkl", "rb") as f:
    model = pickle.load(f)

print("Occupado AI loaded!")
print("----------------------------")
print("Enter booking details below:")
print("----------------------------")

booking = {
    "lead_time": 3,
    "arrival_date_week_number": 27,
    "stays_in_weekend_nights": 2,
    "stays_in_week_nights": 3,
    "adults": 2,
    "is_repeated_guest": 1,
    "previous_cancellations": 0,
    "previous_bookings_not_canceled": 5,
    "booking_changes": 0,
    "days_in_waiting_list": 0,
    "adr": 150,
    "total_of_special_requests": 3
}

booking_df = pd.DataFrame([booking])
risk_score = model.predict_proba(booking_df)[0][1] * 100

print(f"\nBooking analysed:")
print(f"  Lead time:              {booking['lead_time']} days")
print(f"  Room rate:              EUR {booking['adr']}")
print(f"  Previous cancellations: {booking['previous_cancellations']}")
print(f"  Returning guest:        {'Yes' if booking['is_repeated_guest'] else 'No'}")

print(f"\n CANCELLATION RISK SCORE: {risk_score:.1f}%")

if risk_score >= 70:
    print(" HIGH RISK - Request deposit immediately")
elif risk_score >= 40:
    print(" MEDIUM RISK - Send confirmation reminder")
else:
    print(" LOW RISK - Monitor only")

print("----------------------------")


