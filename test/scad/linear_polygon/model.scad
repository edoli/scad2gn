height = 4;
points = [
    [0, 0],
    [4, 0],
    [3, 2],
    [1, 3]
];

linear_extrude(height = height, center = true)
    polygon(points = points);
