from database import Base, engine
import models  # this import is needed so Base knows about the tables

Base.metadata.create_all(engine)
print("Tables created")