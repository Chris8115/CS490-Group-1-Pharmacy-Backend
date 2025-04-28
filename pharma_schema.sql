BEGIN TRANSACTION;
DROP TABLE IF EXISTS "inventory";
CREATE TABLE "inventory" (
	"inventory_id"	INTEGER NOT NULL,
	"medication_id"	INTEGER NOT NULL,
	"stock"	INTEGER NOT NULL,
	"last_updated"	TIMESTAMP NOT NULL,
	CONSTRAINT "inventory_pk" PRIMARY KEY("inventory_id"),
	CONSTRAINT "medication_id" FOREIGN KEY("medication_id") REFERENCES "medications"("medication_id")
);
DROP TABLE IF EXISTS "medications";
CREATE TABLE "medications" (
	"medication_id"	INTEGER NOT NULL,
	"name"	TEXT NOT NULL,
	"description"	TEXT NOT NULL,
	CONSTRAINT "medications_pk" PRIMARY KEY("medication_id")
);
DROP TABLE IF EXISTS "orders";
CREATE TABLE "orders" (
	"order_id"	INTEGER NOT NULL UNIQUE,
	"medication_id"	INTEGER NOT NULL,
	"status"	TEXT NOT NULL DEFAULT 'pending',
	"patient_id"	INTEGER NOT NULL,
	PRIMARY KEY("order_id"),
	FOREIGN KEY("medication_id") REFERENCES "medications"("medication_id")
);
DROP TABLE IF EXISTS "patients";
CREATE TABLE "patients" (
	"patient_id"	INTEGER NOT NULL UNIQUE,
	"first_name"	TEXT NOT NULL,
	"last_name"	TEXT NOT NULL,
	"medical_history"	TEXT NOT NULL,
	"ssn"	INTEGER NOT NULL,
	PRIMARY KEY("patient_id")
);
DROP TABLE IF EXISTS "pharmacists";
CREATE TABLE "pharmacists" (
	"pharmacist_id"	INTEGER NOT NULL,
	"pharmacy_location"	TEXT NOT NULL,
	"password"	TEXT,
	CONSTRAINT "pharmacists_pk" PRIMARY KEY("pharmacist_id")
);
COMMIT;
