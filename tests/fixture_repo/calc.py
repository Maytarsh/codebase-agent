"""Arithmetic helpers."""


def add(left, right):
    """Return the sum of two numbers."""
    return left + right


def divide(left, right):
    """Return left divided by right."""
    if right == 0:
        raise ValueError("cannot divide by zero")
    return left / right
