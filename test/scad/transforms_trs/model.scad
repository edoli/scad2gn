union() {
    translate([-10, 0, 0])
        cube([3, 4, 5], center = true);

    rotate([0, 45, 0])
        cylinder(h = 8, r = 1.5, center = true, $fn = 48);

    translate([10, 0, 0])
        scale([1.5, 0.75, 1.25])
            sphere(r = 2.5, $fn = 36);
}
