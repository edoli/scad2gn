include <../BOSL2/std.scad>
include <../BOSL2/threading.scad>

/* [Parametri Dado] */
M_Size = 8; // [3, 4, 5, 6, 7, 8, 10, 12, 14]
Altezza_Dado = 6.5; 
// Gioco per stampa 3D (0.2 = stretto, 0.4 = largo)
Slop = 0.4; 

/* [Qualità] */
$fn = 50; 

// --- TABELLE ISO ---
w_iso = (M_Size==3)?5.5 : (M_Size==4)?7 : (M_Size==5)?8 : (M_Size==6)?10 : (M_Size==7)?11 : (M_Size==8)?13 : (M_Size==10)?17 : (M_Size==12)?19 : 22;
p_iso = (M_Size<=3)?0.5 : (M_Size==4)?0.7 : (M_Size==5)?0.8 : (M_Size<=7)?1.0 : (M_Size==8)?1.25 : (M_Size==10)?1.5 : (M_Size==12)?1.75 : 2.0;

// --- GENERAZIONE ---
difference() {
    // 1. IL CORPO (Sempre visibile)
    // Usiamo l'esagono standard di BOSL2
    rect_spiral(d=w_iso, h=Altezza_Dado, $fn=6); // Un modo alternativo per fare l'esagono
    
    // In alternativa, se non vedi rect_spiral, usa questo:
    cylinder(h=Altezza_Dado, d=w_iso / cos(30), $fn=6, anchor=CENTER);

    // 2. IL FORO FILETTATO (Sottrazione)
    // Creiamo un bullone "fantasma" più grande di (Slop * 2) per scavare il dado
    threaded_rod(d=M_Size + (Slop * 2), l=Altezza_Dado + 2, pitch=p_iso, thread_profile="round", anchor=CENTER);
}
