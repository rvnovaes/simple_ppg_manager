from ninja import Schema


class ProgramOut(Schema):
    id: int
    name: str
    acronym: str
    is_active: bool
