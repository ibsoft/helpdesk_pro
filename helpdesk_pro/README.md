# Helpdesk Pro — Flask + PostgreSQL Ticketing System
# 🧭 Helpdesk Pro — Python Flask IT Ticketing System

**Helpdesk Pro** είναι ένα ολοκληρωμένο, μοντέρνο, web-based ticketing system για IT departments, σχεδιασμένο σε **Flask + Bootstrap 5 + FontAwesome + SQLAlchemy**, με πλήρη υποστήριξη ρόλων (Admin / Manager / Technician / User), AJAX modals, dark/light theme, DataTables exports, και responsive UI.  
Υποστηρίζει reporting, comments, attachments, audit logging, και granular access control.

---

## 🚀 Βασικά Χαρακτηριστικά

- **Role-based access control**
  - `Admin`: πλήρης πρόσβαση σε όλα τα tickets και χρήστες.
  - `Manager`: πρόσβαση μόνο σε tickets του δικού του τμήματος + δυνατότητα ανάθεσης σε technicians.
  - `Technician`: εργασία σε assigned tickets.
  - `User`: προβολή / δημιουργία μόνο δικών του tickets.
- **Προηγμένο UI**
  - Bootstrap 5 responsive design, mobile-friendly.
  - Dark/Light theme toggle (αυτόματη αποθήκευση σε LocalStorage).
  - FontAwesome icons + animated gradient navbar/footer.
- **AJAX modals**
  - Προσθήκη, Επεξεργασία, Επισκόπηση tickets χωρίς reload.
  - Δυναμικά flash / toast messages.
- **Audit logging**
  - Κάθε ενέργεια (create, edit, comment, upload, delete) αποθηκεύεται στη βάση.
- **Attachments & Comments**
  - Ανέβασμα αρχείων ανά ticket, σε / static/uploads.
  - Threaded comments με χρονοσήμανση.
- **Localization**
  - EN/EL υποστήριξη, με επιλογή γλώσσας από navbar.
- **DataTables**
  - Sorting, Filtering, Pagination, Excel/Print Export.

---

## 🧩 Τεχνολογίες

| Επίπεδο | Stack |
|----------|--------|
| **Backend** | Flask (3.x) + SQLAlchemy + Flask-Login + Flask-WTF + CSRF |
| **Frontend** | Bootstrap 5 + FontAwesome 6 + jQuery + DataTables |
| **Database** | PostgreSQL ή SQLite (ανά περιβάλλον) |
| **Security** | CSRF protection, Session encryption, DPAPI (Windows) ή AES keys (Linux) |
| **Deployment** | Gunicorn / Nginx / Systemd ή Docker |
| **Timezone** | Europe/Athens (UTC → Local conversion με zoneinfo) |

---

## 📂 Δομή Αρχείων

```
helpdesk_pro/
│
├── app/
│   ├── __init__.py
│   ├── models/
│   │   ├── user.py
│   │   ├── ticket.py
│   │   └── __init__.py
│   ├── auth/
│   │   └── routes.py
│   ├── tickets/
│   │   ├── routes.py
│   │   ├── templates/
│   │   │   ├── list.html
│   │   │   ├── view.html
│   │   │   └── edit.html
│   │   └── __init__.py
│   ├── static/
│   │   ├── uploads/
│   │   └── datatables/
│   └── templates/
│       ├── base.html
│       ├── login.html
│       ├── dashboard.html
│       └── index.html
│
├── migrations/
├── config.py
├── requirements.txt
├── run.py
└── README.md
```

---

## ⚙️ Εγκατάσταση (Development Setup)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask db upgrade
flask run
```

---

## 🧰 Αρχική Ρύθμιση Διαχειριστή

Κατά την πρώτη εκκίνηση, αν η βάση είναι άδεια:
- Δημιουργείται Admin (`admin` / `admin123`)
- Αλλαγή κωδικού άμεσα σε παραγωγή.

---

## 🔐 Roles & Permissions

| Ρόλος | Δικαιώματα |
|--------|-------------|
| Admin | Όλα τα tickets & users |
| Manager | Tickets του department & assign |
| Technician | Assigned tickets |
| User | Δικά του tickets |

---

## 🧠 Best Practices

- CSRF tokens σε όλες τις φόρμες
- secure_filename για uploads
- ZoneInfo timezone handling
- Rollback σε exceptions
- Audit logging για ISO 27001 / NIS2 compliance

---

© 2025 Ioannis A. Bouhras — Licensed under MIT License

<img width="1920" height="1020" alt="image" src="https://github.com/user-attachments/assets/9a24db3b-41d6-491d-beda-a864daf787b1" />
<img width="1920" height="1020" alt="image" src="https://github.com/user-attachments/assets/7a1d9d0b-40fc-4516-82e1-f83037fb7b74" />
<img width="1920" height="1020" alt="image" src="https://github.com/user-attachments/assets/041889a1-06fe-40ef-9fac-6fe18df11ed0" />
<img width="1920" height="1020" alt="image" src="https://github.com/user-attachments/assets/ed13d04a-bec2-4059-b943-643c29b7c13b" />


