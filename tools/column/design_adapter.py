"""Column calculation boundary, wholly independent of CAD and floor code."""

from .calculation import check_column, design_column


class ColumnDesignAdapter:
    def design(self, model):
        return design_column(model)


class ColumnCheckAdapter:
    def check(self, model, actual):
        return check_column(model, actual)
