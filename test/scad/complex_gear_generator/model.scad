include <../BOSL2/std.scad>;
include <../BOSL2/gears.scad>;

/**
 * Gear Generator
 *      
 * Author: Jason Koolman
 * Version: 1.1
 *
 * Description:
 * This OpenSCAD script generates a variety of gears using BOSL2, including spur, 
 * ring, crown, bevel, worm gears, and gear racks. It supports customization of 
 * parameters such as circular pitch, module, teeth count, pressure angle, and more.
 *
 * License:
 * This script is shared under the CC BY 4.0 license, meaning you are free to
 * to use, modify, and share under the term that you give appropriate credit.
 *
 * Changelog:
 * [v1.1]
 * - Implemented gear racks.
 * - Improved parameter controls.
 * [v1.2]
 * - Fixed an issue with top faces in MW Customizer for the worm gear.
 * [v1.3]
 * - Added support for straight bevel gears using cutter radius.
 * [v1.4]
 * - Added a worm type that mates with a worm gear.
 * - Added support for defining gear size by module or circular pitch.
 */

/* [⚙️ General] */

// Select the gear type to display.
Gear = "spur"; // [spur: Spur Gear, ring: Ring Gear, crown: Crown Gear, bevel: Bevel Gear, worm: Worm Gear, mating_worm: Mating Worm, rack: Gear Rack]

// Define gear size using circular pitch or module.
Mode = "circ_pitch"; // [circ_pitch: Circular Pitch, mod: Module]

// Set circular pitch or module (based on mode).
Size = 5;

// Number of teeth on the gear.
Teeth = 20;

// Thickness of the gear body.
Thickness = 6;

// Gap at the bottom of the inter-tooth valleys.
Clearance = 0.4;

// Gap between two meshing teeth.
Backlash = 0;

/* [Spur Gear] */

// Pressure angle for tooth profile.
Spur_Pressure_Angle = 20; // [0:1:30]

// Diameter of the central hole.
Spur_Shaft_Diam = 5;

// Helical angle of the teeth.
Spur_Helical = 0; // [0:1:60]

// Enables herringbone gears when helical angle is set.
Spur_Herringbone = false;

/* [Ring Gear] */

// Pressure angle for tooth profile.
Ring_Pressure_Angle = 0; // [0:1:30]

// Thickness of the ring gear backing.
Ring_Backing = 2;

// Helical angle of the teeth.
Ring_Helical = 0; // [0:1:60]

/* [Crown Gear] */

// Pressure angle for tooth profile.
Crown_Pressure_Angle = 20; // [0:1:30]

// Width of the toothed surface from inside to outside.
Crown_Face_Width = 2;

/* [Bevel Gear] */

// Number of teeth on the mating gear.
Bevel_Mate_Teeth = 20;

// Angle between the shafts of the bevel gears.
Bevel_Shaft_Angle = 90; // [0:1:180]

// Diameter of the gear shaft.
Bevel_Shaft_Diam = 5;

// Base angle for spiral teeth.
Bevel_Spiral = 30; // [0:1:45]

// Cutter radius (-1 = auto, 0 = straight).
Bevel_Cutter_Radius = -1;

// If true, generates right-handed spiral teeth.
Bevel_Right_Handed = false;

/* [Worm Gear] */

// Pitch diameter of the worm gear to match to.
Worm_Diam = 30;

// Number of lead starts on the worm gear.
Worm_Starts = 1;

// Arc of the worm gear to mate with (in degrees).
Worm_Arc = 45; // [1:1:60]

// Oversizing factor for the virtual hobbing cutter used for teeth.
Worm_Crowning = 1;

// If true, generates left-handed spiral teeth.
Worm_Left_Handed = false;

// Pressure angle for tooth profile.
Worm_Pressure_Angle = 20; // [0:1:30]

// Length of the mating worm
Mating_Worm_Length = 30;

/* [Gear Rack] */

// Distance from bottom of rack to the roots of the teeth.
Rack_Backing = 2;

// Helical angle of the teeth perpendicular to the rack length.
Rack_Helical = 0; // [0:1:60]

// If true, and helical is set, creates a herringbone rack.
Rack_Herringbone = false;

// Pressure angle for tooth profile.
Rack_Pressure_Angle = 20; // [0:1:30]

/* [📷 Render] */

// Render resolution to control detail level.
Resolution = 3; // [4: Ultra, 3: High, 2: Medium, 1: Low]

// Color of the gear.
Color = "#d2eeff"; // color

// Determine face angle and size based on resolution
Face = (Resolution == 4) ? [1, 0.1]
    : (Resolution == 3) ? [2, 0.2]
    : (Resolution == 2) ? [3, 0.2]
    : [4, 0.4];

$fa = Face[0];
$fs = Face[1];

/* [Hidden] */

_Circ_Pitch = Mode == "circ_pitch" ? Size : undef;
_Mod = Mode == "mod" ? Size : undef;

// Render
color(Color)
generate_gear();

/**
 * Renders the selected gear type.
 */
module generate_gear() {
    if (Gear == "spur") {
        spur_gear(
            circ_pitch = _Circ_Pitch,
            mod = _Mod,
            teeth = Teeth,
            thickness = Thickness,
            pressure_angle = Spur_Pressure_Angle,
            shaft_diam = Spur_Shaft_Diam,
            helical = Spur_Helical,
            herringbone = Spur_Herringbone,
            backlash = Backlash,
            clearance = Clearance
        );
    } else if (Gear == "ring") {
        ring_gear(
            circ_pitch = _Circ_Pitch,
            mod = _Mod,
            teeth = Teeth,
            thickness = Thickness,
            pressure_angle = Ring_Pressure_Angle,
            backing = Ring_Backing,
            helical = Ring_Helical,
            backlash = Backlash,
            clearance = Clearance
        );
    } else if (Gear == "crown") {
        crown_gear(
            circ_pitch = _Circ_Pitch,
            mod = _Mod,
            teeth = Teeth,
            thickness = Thickness,
            face_width = Crown_Face_Width,
            pressure_angle = Crown_Pressure_Angle,
            backlash = Backlash,
            clearance = Clearance
            
        );
    } else if (Gear == "bevel") {
        bevel_gear(
            circ_pitch = _Circ_Pitch,
            mod = _Mod,
            teeth = Teeth,
            thickness = Thickness,
            mate_teeth = Bevel_Mate_Teeth,
            shaft_angle = min(179.99, Bevel_Shaft_Angle),
            shaft_diam = Bevel_Shaft_Diam,
            spiral = Bevel_Spiral,
            cutter_radius = Bevel_Cutter_Radius >= 0 ? Bevel_Cutter_Radius : undef,
            right_handed = Bevel_Right_Handed,
            backlash = Backlash,
            clearance = Clearance
        );
    } else if (Gear == "worm") {
        difference() {
            worm_gear(
                circ_pitch = _Circ_Pitch,
                mod = _Mod,
                teeth = Teeth,
                worm_diam = Worm_Diam,
                worm_starts = Worm_Starts,
                worm_arc = Worm_Arc,
                crowning = Worm_Crowning,
                left_handed = Worm_Left_Handed,
                pressure_angle = Worm_Pressure_Angle,
                backlash = Backlash,
                clearance = Clearance
            );
            thickness = worm_gear_thickness(
                circ_pitch = _Circ_Pitch,
                mod = _Mod,
                teeth = Teeth,
                worm_diam = Worm_Diam,
                worm_arc = Worm_Arc,
                crowning = Worm_Crowning,
                clearance = Clearance
            );
            slice = 0.01;
            up(thickness / 2 - slice / 2)
                cube([500, 500, slice], center = true);
        }
    } else if (Gear == "mating_worm") {
        worm(
            circ_pitch = _Circ_Pitch,
            mod = _Mod,
            d = Worm_Diam,
            l = Mating_Worm_Length,
            starts = Worm_Starts,
            left_handed = Worm_Left_Handed,
            pressure_angle = Worm_Pressure_Angle,
            backlash = Backlash,
            clearance = Clearance,
            $fa = $fa * 2,
            $fs = $fs * 2
        );
    } else if (Gear == "rack") {
        rack(
            pitch = _Circ_Pitch,
            mod = _Mod,
            teeth = Teeth,
            thickness = Thickness,
            backing = Rack_Backing,
            helical = Rack_Helical,
            herringbone = Rack_Herringbone,
            pressure_angle = Rack_Pressure_Angle,
            backlash = Backlash,
            clearance = Clearance
        );
    }
}
