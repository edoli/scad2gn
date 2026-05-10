count = 3;
enabled = true;
mode = "rack";
step = 3.0;

module peg(offset, radius = 0.6) {
    translate([offset, 0, 0])
        cylinder(h = 4, r = radius, center = true, $fn = 32);
}

module rack(step_size, item_count) {
    for (i = [0:item_count - 1]) {
        peg(i * step_size, 0.5 + (i * 0.1));
    }
}

if (enabled && mode == "rack") {
    rack(step, count);
} else {
    cube([1, 1, 1], center = true);
}
