/* =====================================================================
   ULTIMATE PARAMETRIC HARDWARE SYSTEM (Caps, Knobs & Protectors)
   ===================================================================== */

/* [Hardware Selection] */
// Choose metric bolt/nut size (M1 to M16) OR Shaft Diameter for Motors/Pots
Metric_Size = 8; // [1, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 14, 15, 16]

// What hardware are you hiding inside?
Hardware_Type = 1; // [1:Standard Nut (with bolt clearance), 2:Dome/Acorn Nut, 3:Bolt Head (flat), 4:D-Shaft (Motor), 5:Splined Shaft (Potentiometer)]

// If Standard Nut (Type 1), how much does the bolt protrude above the nut? (mm)
Thread_Protrusion = 5.0; // [0.0:0.5:50.0]

/* [Grub Screw Options] */
// Add a side hole for a Set/Grub Screw? (Perfect for D-Shafts & Motors)
Add_Grub_Screw = false;
Grub_Screw_Size = 3; // [2:0.5:5]

/* [What to Generate] */
Render_Mode = 3; // [1:Basic Dome Cap, 2:TPU Floor Protector (Brim), 3:Star Knob, 4:Knurled Knob, 5:Wing Nut Knob, 6:Daisy/Scalloped Knob, 7:T-Handle Knob]

/* [Tolerances & Walls] */
// 0.15 for hard plastic (PLA/PETG) press-fit, 0.0 to -0.1 for TPU (flexible)
Press_Fit_Tolerance = 0.15; // [-0.2:0.05:0.5]
Wall_Thickness = 2.0; // [1.0:0.2:5.0]

/* [Edge Styling] */
// Top edge finish for flat knobs (Modes 3, 4, 6)
Edge_Type = 1; // [1:Chamfer (Straight/Industrial), 2:Fillet (Smooth/Rounded)]

/* [Neck / Standoff Options (Knobs Only)] */
// Add a standoff neck to the bottom? (0 = Disable)
Neck_Length = 8.0; // [0.0:0.5:50.0]
// Diameter of the neck base (Will auto-expand if too small for hardware)
Neck_Diameter = 16.0; // [5.0:0.5:50.0]
// The height of the smooth parabolic transition (flare) to the main body
Neck_Flare_Height = 8.0; // [1.0:0.5:50.0]

/* [Cap & Protector Options (Modes 1 & 2)] */
// Extra skirt length below the nut to cover exposed threads or washers
Cap_Skirt_Length = 5.0; // [0.0:0.5:50.0]
// Thickness of the wide floor pad (brim) in mm (Mode 2 only)
Protector_Brim_Thickness = 4.0; // [2.0:0.5:15.0]

/* [Knob Options (Modes 3 to 7)] */
// Thickness of the solid plastic under the nut/bolt head (Safety constrained to min 2mm)
Knob_Base_Thickness = 5.0; // [2.0:0.5:20.0]
// Outer diameter for all knobs (except Wing Nut)
Knob_Diameter = 35; // [15:1:80]
// Number of arms for Star Knob (Mode 3 only)
Star_Arms = 4; // [3:1:8]

/* [Wing Nut Options (Mode 5)] */
// Total width from wing tip to wing tip
Wing_Span = 50; // [20:1:120]
// Total height of the wings from the bottom
Wing_Height = 25; // [10:1:80]

/* [Hidden] */
$fn = 64;

// --- STANDARDIZED MEASUREMENT TABLE (DIN 934) ---
function get_dims(m) =
    (m==1) ? [2.5, 0.8] :
    (m==2) ? [4.0, 1.6] :
    (m==2.5)? [5.0, 2.0] :
    (m==3) ? [5.5, 2.4] :
    (m==4) ? [7.0, 3.2] :
    (m==5) ? [8.0, 4.0] :
    (m==6) ? [10.0, 5.0] :
    (m==8) ? [13.0, 6.5] :
    (m==10)? [17.0, 8.0] :
    (m==12)? [19.0, 10.0] :
    (m==14)? [22.0, 11.0] :
    (m==15)? [24.0, 12.0] : 
    (m==16)? [24.0, 13.0] : [0,0];

dims = get_dims(Metric_Size);
waf = dims[0];
nut_h = dims[1];

hex_rad = ((waf + Press_Fit_Tolerance) / 2) / 0.866025;
thread_clearance_rad = (Metric_Size + 0.5) / 2;

// Adapt pocket depth and radius for Electronics shafts (Motors/Pots usually need ~12mm depth)
pocket_depth = (Hardware_Type >= 4) ? max(nut_h, 12) : nut_h;
pocket_rad = (Metric_Size + Press_Fit_Tolerance) / 2;

// Safe base thickness (guarantees at least 2mm of solid plastic "meat")
safe_base_thick = max(2.0, Knob_Base_Thickness);

// Calculate internal height (Added Cap_Skirt_Length to extend the base seamlessly)
base_internal_h = (Hardware_Type == 1) ? (pocket_depth + Thread_Protrusion) : 
                  (Hardware_Type == 2) ? (pocket_depth + hex_rad) : 
                  pocket_depth;

total_internal_h = base_internal_h + Cap_Skirt_Length;

// --- NECK ADDITION MATH ---
// Calculate added height only for knobs and if neck length is > 0
added_h = (Render_Mode >= 3 && Neck_Length > 0) ? (Neck_Length + Neck_Flare_Height) : 0;
// Ensure neck is at least thick enough to hold the hardware plus walls
safe_neck_dia = max(Neck_Diameter, (pocket_rad * 2) + (Wall_Thickness * 2));

// Outer height logic: For knobs, height is nut height + solid base + neck. For caps, it's internal height + walls.
outer_h = (Render_Mode >= 3) ? (pocket_depth + safe_base_thick + added_h) : (total_internal_h + Wall_Thickness);
outer_rad = hex_rad + Wall_Thickness;

/* =====================================================================
   HELPER MODULES
   ===================================================================== */
// Tool to apply the Parabolic Neck Flare to any Knob
module apply_neck_flare(knob_radius) {
    if (added_h > 0) {
        intersection() {
            children(); // Original knob shape

            // Parabolic "Trumpet" profile
            rotate_extrude($fn=64) {
                polygon(points=concat(
                    [[0, 0]],
                    [[safe_neck_dia/2, 0]],
                    // Straight Neck part
                    [[safe_neck_dia/2, Neck_Length]],
                    // Parabolic transition (Pola Parabole)
                    [for(i=[1:15]) 
                        let(t = i/15,
                            z = Neck_Length + t * Neck_Flare_Height,
                            r = safe_neck_dia/2 + (knob_radius - safe_neck_dia/2) * pow(t, 2)) 
                        [r, z]
                    ],
                    // Top bound to let the rest of the knob pass untouched
                    [[knob_radius + 20, Neck_Length + Neck_Flare_Height]],
                    [[knob_radius + 20, outer_h + 20]],
                    [[0, outer_h + 20]]
                ));
            }
        }
    } else {
        children();
    }
}

module top_chamfer_tool(radius, chamfer) {
    translate([0, 0, outer_h - chamfer])
    difference() {
        cylinder(r=radius + 10, h=chamfer + 1);
        translate([0, 0, -0.01]) {
            if (Edge_Type == 1) {
                // Chamfer (Straight cut)
                cylinder(r1=radius, r2=radius - chamfer, h=chamfer + 0.02);
            } else {
                // Fillet (Rounded cut)
                union() {
                    cylinder(r=radius - chamfer, h=chamfer + 0.02);
                    rotate_extrude()
                        translate([radius - chamfer, 0, 0])
                        intersection() {
                            circle(r=chamfer, $fn=32);
                            square([chamfer, chamfer]);
                        }
                }
            }
        }
    }
}

// Generates the specific pocket shape (Hex, D-Shaft, or Splined)
    module hardware_pocket(h_val = pocket_depth) {
        if (Hardware_Type <= 3) {
            cylinder(r=hex_rad, h=h_val + 0.1, $fn=6);
        } else if (Hardware_Type == 4) {
            // D-Shaft for Motors
            difference() {
                cylinder(r=pocket_rad, h=h_val + 0.1);
                flat_w = pocket_rad * 0.35; 
                translate([-pocket_rad, pocket_rad - flat_w, -0.1])
                    cube([pocket_rad*2, pocket_rad, h_val + 0.3]);
            }
        } else if (Hardware_Type == 5) {
            // Splined Potentiometer
            union() {
                cylinder(r=pocket_rad - 0.25, h=h_val + 0.1); 
                for(i=[0:17]) { 
                    rotate([0, 0, i * 20])
                    translate([pocket_rad - 0.25, 0, 0])
                        cylinder(r=0.4, h=h_val + 0.1, $fn=8);
                }
            }
        }
    }

/* =====================================================================
   INTERNAL VOID MODULES
   ===================================================================== */
module internal_void() {
    if (Render_Mode == 1) {
            // CAPS (Mode 1): Zbog suknjice, matica ide skroz do dna
            translate([0, 0, -0.1]) {
                
                // Rastežemo šesterokutni (ili drugi) profil kroz džep + suknjicu!
                hardware_pocket(pocket_depth + Cap_Skirt_Length);
                
                // Praznina iznad matice za višak vijka (ili obli krov za Acorn maticu) počinje TEK IZNAD matice
                translate([0, 0, pocket_depth + Cap_Skirt_Length]) {
                    if (Hardware_Type == 1 && Thread_Protrusion > 0) {
                        cylinder(r=thread_clearance_rad, h=Thread_Protrusion + 0.15);
                    } else if (Hardware_Type == 2) {
                        sphere(r=hex_rad, $fn=32);
                    }
                }
            }
    } else if (Render_Mode >= 3) {
        // KNOBS (Modes 3 to 7)
        union() {
            if (Hardware_Type <= 3) {
                // NUTS & BOLTS: Hex pocket on TOP, pass-through hole for bolt
                translate([0, 0, -0.1])
                    cylinder(r=thread_clearance_rad, h=outer_h + 50);
                    
                translate([0, 0, outer_h - pocket_depth])
                    hardware_pocket();
            } else {
                // MOTORS & POTS: Blind pocket from the BOTTOM
                translate([0, 0, -0.1])
                    hardware_pocket();
            }
                
            // Set Screw / Grub Screw side hole
            if (Add_Grub_Screw) {
                // Ensure screw aligns with the pocket regardless of where the pocket is
                grub_z = (Hardware_Type <= 3) ? (outer_h - (pocket_depth / 2)) : (pocket_depth / 2);
                
                translate([0, 0, grub_z])
                rotate([0, 0, 90]) // Aligned to +Y axis to hit the D-shaft flat perfectly
                rotate([0, 90, 0])
                    cylinder(r=(Grub_Screw_Size + 0.4) / 2, h=Knob_Diameter + 20);
            }
        }
    }
}

/* =====================================================================
   OUTER SHELL MODULES (Caps & Protectors)
   ===================================================================== */
module basic_cap() {
    difference() {
        union() {
            cylinder(r=outer_rad, h=total_internal_h);
            translate([0, 0, total_internal_h])
                intersection() {
                    sphere(r=outer_rad);
                    cylinder(r=outer_rad+1, h=outer_rad+1);
                }
        }
        internal_void();
    }
}

// --- REDESIGNED FLOOR PROTECTOR (FLIPPED, CUSTOMIZABLE BRIM) ---
module tpu_floor_protector() {
    brim_rad = outer_rad + 6;
    brim_thick = Protector_Brim_Thickness;
    total_h = brim_thick + total_internal_h;
    
    // Ukupna dubina džepa sada uključuje i produženi vrat (skirt)
    extended_pocket = pocket_depth + Cap_Skirt_Length;

    difference() {
        union() {
            hull() {
                cylinder(r=brim_rad - 2, h=0.01);
                rotate_extrude() translate([brim_rad - 2, 2, 0]) circle(r=2);
                translate([0, 0, brim_thick]) cylinder(r=outer_rad, h=0.01);
            }
            translate([0, 0, brim_thick])
                cylinder(r=outer_rad, h=total_internal_h);
        }
        
        // --- RUPA ZA MATICU/OSOVINU S GORNJE STRANE ---
        // Rastežemo džep duboko kroz vrat!
        translate([0, 0, total_h - extended_pocket])
            hardware_pocket(extended_pocket);
            
        // Praznina za višak vijka (ili kugla za acorn maticu) pomiče se ispod džepa
        if (Hardware_Type == 1 && Thread_Protrusion > 0) {
            // Sigurnosna provjera da vijak ne probije pod! (Uvijek ostaje 1.5mm mesa)
            max_depth = min(Thread_Protrusion, total_h - extended_pocket - 1.5);
            if (max_depth > 0) {
                translate([0, 0, total_h - extended_pocket - max_depth])
                    cylinder(r=thread_clearance_rad, h=max_depth + 0.1);
            }
        } else if (Hardware_Type == 2) {
            translate([0, 0, total_h - extended_pocket])
                sphere(r=hex_rad, $fn=32);
        }
    }
}

/* =====================================================================
   OUTER SHELL MODULES (Knobs)
   ===================================================================== */
module star_knob() {
    center_rad = Knob_Diameter / 3;
    difference() {
        apply_neck_flare(Knob_Diameter/2) {
            union() {
                for (i = [0 : Star_Arms - 1]) {
                    rotate([0, 0, i * (360 / Star_Arms)])
                    hull() {
                        cylinder(r=center_rad, h=outer_h);
                        translate([Knob_Diameter/2 - center_rad/2, 0, 0])
                            cylinder(r=center_rad/2, h=outer_h);
                    }
                }
                cylinder(r=center_rad + 1, h=outer_h);
            }
        }
        top_chamfer_tool(Knob_Diameter/2, 2);
        internal_void();
    }
}

module knurled_knob() {
    knurl_count = 24;
    knurl_rad = Knob_Diameter / 2;
    difference() {
        apply_neck_flare(knurl_rad) {
            union() {
                cylinder(r=knurl_rad - 1, h=outer_h);
                for (i = [0 : knurl_count - 1]) {
                    rotate([0, 0, i * (360 / knurl_count)])
                    translate([knurl_rad - 1, 0, 0])
                        cylinder(r=1.5, h=outer_h, $fn=16);
                }
            }
        }
        top_chamfer_tool(knurl_rad + 0.5, 2);
        internal_void();
    }
}

// --- FULLY CUSTOMIZABLE WING NUT ---
module wing_nut_knob() {
    center_hub_rad = max(outer_rad + 2.5, Knob_Diameter / 4);
    wing_tip_thick = 5;
    wing_base_thick = 10;
    
    actual_span = max(Wing_Span / 2, center_hub_rad + 6); 
    wing_tall = max(outer_h + 5, Wing_Height);

    difference() {
        apply_neck_flare(actual_span) {
            union() {
                cylinder(r=center_hub_rad, h=outer_h - 1.5);
                translate([0, 0, outer_h - 1.5])
                    cylinder(r1=center_hub_rad, r2=center_hub_rad - 1.5, h=1.5);
                
                for (a = [0, 180]) {
                    rotate([0, 0, a])
                    hull() {
                        translate([center_hub_rad, 0, 0])
                            cylinder(r=wing_base_thick/2, h=outer_h - 1.5);
                        translate([actual_span - wing_tip_thick/2, 0, 0])
                            cylinder(r=wing_tip_thick/2, h=0.1);
                        translate([actual_span - wing_tip_thick/2, 0, wing_tall - wing_tip_thick/2])
                            sphere(r=wing_tip_thick/2);
                        translate([center_hub_rad + wing_tip_thick, 0, wing_tall - wing_tip_thick/2 - 2])
                            sphere(r=wing_tip_thick/2);
                    }
                }
            }
        }
        internal_void();
    }
}

module daisy_knob() {
    scallop_count = 6;
    base_rad = Knob_Diameter / 2;
    cut_rad = base_rad * 0.35;
    difference() {
        apply_neck_flare(base_rad) {
            difference() {
                cylinder(r=base_rad, h=outer_h);
                for (i = [0 : scallop_count - 1]) {
                    rotate([0, 0, i * (360 / scallop_count)])
                    translate([base_rad + cut_rad*0.1, 0, -1])
                        cylinder(r=cut_rad, h=outer_h + 2);
                }
            }
        }
        top_chamfer_tool(base_rad, 2);
        internal_void();
    }
}

module t_handle_knob() {
    center_hub_rad = max(outer_rad + 2.5, Knob_Diameter / 4);
    handle_len = max(Knob_Diameter * 1.5, center_hub_rad * 4);
    bar_w = center_hub_rad * 1.2; 
    fillet = 2.5; 

    difference() {
        apply_neck_flare(handle_len / 2) {
            union() {
                hull() {
                    for (x = [-handle_len/2 + bar_w/2, handle_len/2 - bar_w/2]) {
                        translate([x, 0, 0]) {
                            cylinder(r=bar_w/2, h=outer_h - fillet);
                            translate([0, 0, outer_h - fillet])
                                rotate_extrude() translate([bar_w/2 - fillet, 0, 0]) circle(r=fillet);
                            translate([0, 0, outer_h - fillet])
                                cylinder(r=bar_w/2 - fillet, h=fillet);
                        }
                    }
                    cylinder(r=center_hub_rad, h=outer_h - fillet);
                    translate([0, 0, outer_h - fillet])
                        cylinder(r1=center_hub_rad, r2=center_hub_rad - fillet, h=fillet);
                }
            }
        }
        internal_void();
    }
}

/* =====================================================================
   RENDER LOGIC
   ===================================================================== */
if (Render_Mode == 1) basic_cap();
else if (Render_Mode == 2) tpu_floor_protector();
else if (Render_Mode == 3) star_knob();
else if (Render_Mode == 4) knurled_knob();
else if (Render_Mode == 5) wing_nut_knob();
else if (Render_Mode == 6) daisy_knob();
else if (Render_Mode == 7) t_handle_knob();