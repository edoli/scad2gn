profile_width = 1.5;
profile_height = 2.0;
radius = 4.0;
detail = 60;
$fn = detail;

rotate_extrude()
    translate([radius, 0, 0])
        square([profile_width, profile_height], center = true);
