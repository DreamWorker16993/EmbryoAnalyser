// --- Recursive Subfolder Processor ---

// main
masterDir = getDirectory("Choose the Master Directory containing subfolders:");  //master directory containing all subfolders


setBatchMode(true); // Runs in background for massive speed boost

processFolder(masterDir);

setBatchMode(false);
print("--- ALL SUBFOLDERS FULLY PROCESSED ---");


// ==========================================
// RECURSIVE DIRECTORY SCANNER
// ==========================================
function processFolder(currentDir) {
    list = getFileList(currentDir);
    
    // First, check if there are images in this specific folder to process
    imageFile = "";
    roiFile = "";
    
    for (i = 0; i < list.length; i++) {
        // If we find a subdirectory, recursively call this function to go deeper
        if (File.isDirectory(currentDir + list[i])) {
            processFolder(currentDir + list[i]);
        }
        
        // Identify the raw image tif file in the current folder
        if (endsWith(toLowerCase(list[i]), ".tif")) {
            imageFile = list[i];
        }
        
        // Identify the corresponding ROI zip file
        if (endsWith(toLowerCase(list[i]), ".zip")) {
            roiFile = list[i];
        }
    }
    
    // If we have an image and an ROI file in this folder, process them!
    if (imageFile != "" && roiFile != "") {
        processTissue(currentDir, imageFile, roiFile);
    }
}


// ==========================================
// SEGMENTATION & MASK EXTRACTION
// ==========================================
function processTissue(dir, imgName, roiName) {
    //print("Processing: " + dir + imgName);
    
    // Clean up anything open in the ROI manager from previous runs
    if (roiManager("count") > 0) {
        roiManager("reset");
    }
    
    // Open the Image and corresponding ROI set
    open(dir + imgName);
    roiManager("Open", dir + roiName);
    
    // Setup and run measurements
    run("Set Measurements...", "area centroid perimeter fit shape feret's redirect=None decimal=3");
    roiManager("Measure");
    saveAs("Results", dir + "measurement.csv");
    run("Clear Results");
    
    // Crop & Save Individual Masks
    roi_count = roiManager("count");
    W = getWidth();
    H = getHeight();
    
    for (i = 0; i < roi_count; i++) {
        roiManager("select", i);
        Roi.getBounds(x, y, w, h); 
        
        thres = 2;
        // Verify cell does not touch boundaries
        if ((x > thres) && (y > thres) && (x + w < W - thres) && (y + h < H - thres)){
            run("Create Mask");
            run("Invert");
            saveAs("PNG", dir + "mask_" + i + ".png");
            close(); // Close the mask image
        }
    }
    
    // Clean up open windows and ROI Manager before moving to next directory
    close("*"); // Closes the original raw image
    roiManager("reset");
}