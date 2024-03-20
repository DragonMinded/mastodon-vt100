class BoundingRectangle:
    def __init__(self, *, top: int, bottom: int, left: int, right: int) -> None:
        self.top: int = top
        self.bottom: int = bottom
        self.left: int = left
        self.right: int = right

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def contains(self, y: int, x: int) -> bool:
        return y >= self.top and y < self.bottom and x >= self.left and x < self.right

    def offset(self, y: int, x: int) -> "BoundingRectangle":
        return BoundingRectangle(
            top=self.top + y,
            bottom=self.bottom + y,
            left=self.left + x,
            right=self.right + x,
        )

    def clip(self, bounds: "BoundingRectangle") -> "BoundingRectangle":
        return BoundingRectangle(
            top=min(max(self.top, bounds.top), bounds.bottom),
            bottom=max(min(self.bottom, bounds.bottom), bounds.top),
            left=min(max(self.left, bounds.left), bounds.right),
            right=max(min(self.right, bounds.right), bounds.left),
        )

    def __repr__(self) -> str:
        return "BoundingRectangle(top={}, bottom={}, left={}, right={})".format(
            self.top, self.bottom, self.left, self.right
        )
