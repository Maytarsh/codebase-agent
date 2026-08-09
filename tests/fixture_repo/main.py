"""Entry point for the fixture project."""

from calc import add, divide


def main():
    print(add(2, 3))
    print(divide(10, 2))


if __name__ == "__main__":
    main()
