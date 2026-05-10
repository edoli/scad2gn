union() {
    resize([6, 4, 2])
        cube([2, 2, 2], center = true);

    translate([10, 0, 0])
        mirror([1, 0, 0])
            cube([3, 2, 4], center = true);

    multmatrix([
        [1, 0, 0, -10],
        [0, 1, 0, 0],
        [0, 0, 1, 2],
        [0, 0, 0, 1]
    ])
        cylinder(h = 5, r = 1.2, center = true, $fn = 40);
}
