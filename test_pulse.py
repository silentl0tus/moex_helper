from sentiment_scraper import extract_pulse_messages
msgs = extract_pulse_messages('SBER', 50)
print('Found:', len(msgs))
