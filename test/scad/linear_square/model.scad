width = 6;
depth = 4;
height = 3;
centered = true;

linear_extrude(height = height, center = centered)
    square([width, depth], center = true);
