radius = 3;
height = 5;
detail = 40;
$fn = detail;

linear_extrude(height = height)
    circle(r = radius);
