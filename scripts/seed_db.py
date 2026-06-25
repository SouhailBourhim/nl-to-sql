"""One-off script to create the sample schema and seed it with synthetic data.

Run once after the Postgres container is up: `python scripts/seed_db.py`
"""
import random
from datetime import date, timedelta

from sqlalchemy import text

from db.connection import engine

random.seed(42)

SCHEMA_SQL = """
DROP TABLE IF EXISTS recharges;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS plans;

CREATE TABLE plans (
    plan_id SERIAL PRIMARY KEY,
    plan_name VARCHAR(50) NOT NULL,
    monthly_price NUMERIC(6,2) NOT NULL
);

CREATE TABLE customers (
    customer_id SERIAL PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) NOT NULL,
    signup_date DATE NOT NULL,
    plan_id INTEGER NOT NULL REFERENCES plans(plan_id),
    status VARCHAR(10) NOT NULL CHECK (status IN ('active', 'churned')),
    churn_date DATE
);

CREATE TABLE recharges (
    recharge_id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    amount NUMERIC(8,2) NOT NULL,
    recharge_date DATE NOT NULL
);
"""

PLANS = [("Basic", 9.99), ("Standard", 19.99), ("Premium", 39.99)]

FIRST_NAMES = ["Amine", "Sara", "Youssef", "Lina", "Karim", "Nadia", "Omar", "Imane",
               "Hassan", "Salma", "Reda", "Fatima", "Walid", "Hind", "Ayoub", "Meryem"]
LAST_NAMES = ["Bennani", "El Amrani", "Tazi", "Idrissi", "Chraibi", "Berrada",
              "Fassi", "Ouazzani", "Lahlou", "Ziani"]

TODAY = date(2026, 6, 25)


def random_date(start: date, end: date) -> date:
    delta_days = (end - start).days
    return start + timedelta(days=random.randint(0, max(delta_days, 0)))


def seed():
    with engine.begin() as conn:
        conn.execute(text(SCHEMA_SQL))

        plan_ids = []
        for name, price in PLANS:
            result = conn.execute(
                text("INSERT INTO plans (plan_name, monthly_price) VALUES (:n, :p) RETURNING plan_id"),
                {"n": name, "p": price},
            )
            plan_ids.append(result.scalar_one())

        customer_ids = []
        for i in range(60):
            signup = random_date(TODAY - timedelta(days=730), TODAY - timedelta(days=30))
            # ~25% of customers have churned; churn date is after signup, weighted recent
            is_churned = random.random() < 0.25
            churn_date = random_date(signup + timedelta(days=15), TODAY) if is_churned else None

            result = conn.execute(
                text("""
                    INSERT INTO customers (first_name, last_name, email, signup_date, plan_id, status, churn_date)
                    VALUES (:fn, :ln, :email, :signup, :plan_id, :status, :churn_date)
                    RETURNING customer_id
                """),
                {
                    "fn": (fn := random.choice(FIRST_NAMES)),
                    "ln": (ln := random.choice(LAST_NAMES)),
                    "email": f"{fn.lower()}.{ln.lower().replace(' ', '')}{i}@example.com",
                    "signup": signup,
                    "plan_id": random.choice(plan_ids),
                    "status": "churned" if is_churned else "active",
                    "churn_date": churn_date,
                },
            )
            customer_ids.append((result.scalar_one(), signup, churn_date, is_churned))

        for customer_id, signup, churn_date, is_churned in customer_ids:
            window_end = churn_date if is_churned else TODAY
            num_recharges = random.randint(0, 12)
            for _ in range(num_recharges):
                conn.execute(
                    text("""
                        INSERT INTO recharges (customer_id, amount, recharge_date)
                        VALUES (:cid, :amount, :rdate)
                    """),
                    {
                        "cid": customer_id,
                        "amount": round(random.uniform(5, 50), 2),
                        "rdate": random_date(signup, window_end),
                    },
                )

    print("Seed complete.")


if __name__ == "__main__":
    seed()
