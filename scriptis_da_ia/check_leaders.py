import pandas as pd

df = pd.read_csv('cards_rows.csv')
leaders = df[df['card_type'].str.upper() == 'LEADER']
result = leaders[leaders['card_name'].str.contains('Imu|Portgas', na=False, regex=True)]
print(result[['card_name', 'card_set_id', 'card_text']].to_string())