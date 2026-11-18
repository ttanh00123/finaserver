# id -> (name, hint)
EXPENSE = {
    9:  ("Food & Drink", "meals, coffee, snacks, restaurants, delivery"),
    10: ("Transport", "taxi, Grab, bus, parking, tolls"),
    11: ("Phone", "phone bill, top-up, data plan"),
    12: ("Internet", "wifi, broadband"),
    13: ("Fuel", "petrol, gas for vehicles"),
    14: ("Groceries", "supermarket, market, cooking ingredients"),
    15: ("Clothing", "clothes, shoes, accessories"),
    16: ("Beauty", "haircut, salon, cosmetics, spa"),
    17: ("Entertainment", "movies, games, subscriptions, karaoke"),
    18: ("Travel", "flights, hotels, tours, trips"),
    19: ("Family Support", "money sent to parents or relatives"),
    20: ("Events & Gifts", "weddings, birthdays, gifts, parties"),
    21: ("Medical", "doctor, hospital, check-up, dentist"),
    22: ("Medicine", "pharmacy, pills, vitamins"),
    23: ("Fitness", "gym, sports, yoga, swimming"),
    24: ("Fund", "savings, emergency fund, set-aside money"),
    25: ("Repair", "fixing vehicles, appliances, house"),
    26: ("Accident", "accident costs, damages"),
    27: ("Fine & Fee", "fines, penalties, bank fees, admin fees"),
    28: ("Rent", "house or room rent"),
    29: ("Electricity", "electric bill"),
    30: ("Water", "water bill"),
    31: ("Education", "tuition, courses, books, school fees"),
    32: ("Insurance", "health, life, vehicle insurance"),
    33: ("Installment", "loan payments, credit card installments"),
    34: ("Other", "only if nothing else fits"),
}

INCOME = {
    1: ("Salary", "monthly pay from a job"),
    2: ("Bonus", "bonus, commission, reward"),
    3: ("Allowance", "allowance, pocket money, stipend"),
    4: ("Business", "sales, shop or freelance income"),
    5: ("Investment", "stocks, crypto, trading profit"),
    6: ("Passive Income", "interest, dividends, rental income"),
    7: ("Gift", "money received as a gift"),
    8: ("Other Income", "only if nothing else fits"),
}

# Used when the model's answer is invalid (same ids your app treats as "Other")
FALLBACK = {"expense": 34, "income": 35}