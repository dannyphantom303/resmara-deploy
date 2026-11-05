from app.db.session import Base, engine
Base.metadata.create_all(bind=engine)
print("Database tables created")
