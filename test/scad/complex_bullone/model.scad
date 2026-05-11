include <../BOSL2/std.scad>
include <../BOSL2/threading.scad>

/* [Misure Bullone] */
// Misura metrica (M3-M14)
M_Size = 8; // [3:M3, 4:M4, 5:M5, 6:M6, 7:M7, 8:M8, 10:M10, 12:M12, 14:M14]

// Lunghezza della parte filettata (mm)
Lunghezza_Vite = 20; 

// Spessore della testa esagonale (mm)
Spessore_Testa = 5.5;

/* [Tolleranza Stampa 3D] */
// Riduzione diametro per avvitamento (0.2 è perfetto con il dado a 0.2)
Slop_Bullone = 0.2; 

/* [Qualità] */
$fn = 64; 

// --- TABELLE ISO ---
w_iso = (M_Size==3)?5.5 : (M_Size==4)?7 : (M_Size==5)?8 : (M_Size==6)?10 : (M_Size==7)?11 : (M_Size==8)?13 : (M_Size==10)?17 : (M_Size==12)?19 : 22;
p_iso = (M_Size<=3)?0.5 : (M_Size==4)?0.7 : (M_Size==5)?0.8 : (M_Size<=7)?1.0 : (M_Size==8)?1.25 : (M_Size==10)?1.5 : (M_Size==12)?1.75 : 2.0;

// --- GENERAZIONE ---
union() {
    // 1. TESTA ESAGONALE
    cylinder(h=Spessore_Testa, d=w_iso / cos(30), $fn=6, anchor=BOTTOM);
    
    // 2. FILETTO CON TOLLERANZA E PUNTA SMUSSATA
    translate([0, 0, Spessore_Testa])
        threaded_rod(
            d = M_Size - (Slop_Bullone), // Riduce il diametro totale
            l = Lunghezza_Vite, 
            pitch = p_iso, 
            thread_profile = "round", 
            bevel = true,               // Aggiunge un piccolo invito in punta
            anchor = BOTTOM
        );
}
