# Development

Backend entry: `backend/app/main.py`; frontend entry: `frontend/src/main.tsx`; REST API documentation: `/docs`. Data are stored in a mounted `data/` directory; PostgreSQL stores recording metadata and annotations. Frontend uses native Canvas 2D, synchronous sample coordinate conversion and fetch-based API calls. This compact prototype needs decomposition into feature modules before major additions. `DATABASE_URL` supports SQLite and PostgreSQL. The database is initialized using `create_all`, not migrations.
