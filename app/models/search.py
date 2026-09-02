from datetime import date

from pydantic import BaseModel, Field, model_validator


class HotelSearch(BaseModel):
    city: str = Field(min_length=2, max_length=100)
    hotel_name: str | None = Field(default=None, max_length=200)
    check_in: date
    check_out: date
    rooms: int = Field(ge=1, le=10)
    adults: int = Field(ge=1, le=20)
    children: int = Field(ge=0, le=10)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.check_in < date.today():
            raise ValueError("Check-in cannot be in the past.")

        if self.check_out <= self.check_in:
            raise ValueError("Check-out must be after check-in.")

        return self
