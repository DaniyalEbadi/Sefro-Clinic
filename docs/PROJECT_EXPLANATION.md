1. Sefro Clinic is a backend system for managing a beauty clinic.
2. The project is built with Django and Django REST Framework.
3. The API documentation is available through Swagger at `/api/docs/`.
4. The OpenAPI schema is available at `/api/schema/`.
5. The system is designed as a backend-only service.
6. Frontend pages are not included in this project.
7. Authentication is handled with JWT tokens.
8. Login is done through `POST /api/auth/token/`.
9. The access token and refresh token are stored in HTTP-only cookies.
10. HTTP-only cookies help protect tokens from browser JavaScript access.
11. Token refresh is done through `POST /api/auth/token/refresh/`.
12. Logout is done through `POST /api/auth/logout/`.
13. The logout endpoint clears both authentication cookies.
14. The current logged-in user can be checked with `GET /api/auth/me/`.
15. The default admin user is created from project settings.
16. Normal users cannot create another admin account through the API.
17. Employee accounts can be created by the admin.
18. Employee creation is available at `POST /api/auth/employees/`.
19. Passwords are never saved as plain text.
20. Django hashes passwords before saving them in the database.
21. The project uses Argon2id as the main password hashing algorithm.
22. Argon2id is a strong memory-hard algorithm for password storage.
23. The customer module stores clinic customer profiles.
24. A customer has first name, last name, mobile number, national ID, and Bitmoji code.
25. Customers can be searched by name, phone, national ID, or Bitmoji code.
26. Customer endpoints are available under `/api/customers/`.
27. The visit module records every customer visit.
28. Each visit can include one or more selected services.
29. Supported services can include doctor visit, facial, laser, and carbon therapy.
30. A customer becomes loyal after five registered visits.
31. Visit endpoints are available under `/api/visits/`.
32. The payment module stores customer payments.
33. Payments can be connected to a customer and optionally to a visit.
34. Payment endpoints are available under `/api/payments/`.
35. Dashboard data is available through `GET /api/dashboard/`.
36. The dashboard returns customer count, loyal customer count, and sales summaries.
37. Sales summaries include daily, weekly, monthly, and yearly values.
41. The product module stores products used or sold by the clinic.
42. Product endpoints are available under `/api/inventory/products/`.
43. The inventory module tracks product stock levels.
44. Inventory items include quantity and minimum quantity.
45. Low stock status is calculated automatically.
46. Inventory item endpoints are available under `/api/inventory/items/`.
47. Stock movements record product entry and exit from inventory.
48. Stock movement endpoints are available under `/api/inventory/movements/`.
49. Swagger groups endpoints by clear categories like Authentication, Customers, Payments, and Inventory.
50. This structure keeps the backend organized, secure, and ready for a future frontend or mobile app.
