from sentiment_scraper import extract_pulse_messages, extract_meaningful_messages

print("Testing Smart-Lab...")
sl_msgs = extract_meaningful_messages("SBER", max_pages=1, max_messages=5)
print(f"Smart-Lab SBER: {len(sl_msgs)} messages")

print("Testing Pulse...")
pulse_msgs = extract_pulse_messages("SBER", max_messages=5)
print(f"Pulse SBER: {len(pulse_msgs)} messages")
