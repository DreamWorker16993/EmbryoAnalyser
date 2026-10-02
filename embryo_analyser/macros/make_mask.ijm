// Batch morphology measurements and individual cell masks from paired TIFF/ROI inputs.
// The Python workflow runs this macro on protected input copies in a fresh folder.
masterDir = getDirectory("Choose the Master Directory containing subfolders:");
outputDir = getDirectory("Choose the output directory:");
measureCells = true;
exportMasks = true;

// Direct Fiji use also keeps generated files outside the dataset and input tree.
normalizedOutput = replace(outputDir, "\\", "/");
if (indexOf(toLowerCase(normalizedOutput), "/dataset/") >= 0)
    exit("Choose an output directory outside dataset.");
if (startsWith(outputDir, masterDir))
    exit("Choose an output directory outside the input directory.");
setBatchMode(true);
processFolder(masterDir, "");
setBatchMode(false);
print("--- ALL SUBFOLDERS FULLY PROCESSED ---");

function processFolder(currentDir, relativeDir) {
    list = getFileList(currentDir);
    imageCount = 0;
    zipCount = 0;
    soleZip = "";
    for (i = 0; i < list.length; i++) {
        name = toLowerCase(list[i]);
        if (endsWith(name, ".tif") || endsWith(name, ".tiff")) imageCount++;
        if (endsWith(name, ".zip")) { zipCount++; soleZip = list[i]; }
    }
    for (i = 0; i < list.length; i++) {
        name = list[i];
        if (File.isDirectory(currentDir + name)) {
            processFolder(currentDir + name, relativeDir + name);
        } else if (endsWith(toLowerCase(name), ".tif") || endsWith(toLowerCase(name), ".tiff")) {
            stem = substring(name, 0, lastIndexOf(name, "."));
            roiName = "";
            for (j = 0; j < list.length; j++)
                if (toLowerCase(list[j]) == toLowerCase(stem + "_rois.zip")) roiName = list[j];
            // Legacy ZIP names are accepted only in a one-image/one-ZIP folder.
            if (roiName == "" && imageCount == 1 && zipCount == 1) roiName = soleZip;
            if (roiName == "") exit("Missing or ambiguous ROI ZIP for " + currentDir + name);
            destination = outputDir + relativeDir + stem + "/";
            if (File.exists(destination)) exit("Output already exists: " + destination);
            File.makeDirectory(destination);
            processTissue(currentDir, name, roiName, destination);
        }
    }
}

function processTissue(dir, imgName, roiName, destination) {
    roiManager("reset");
    open(dir + imgName);
    roiManager("Open", dir + roiName);
    if (roiManager("count") == 0) exit("No cell ROIs for " + imgName);
    // Preserve the original measurement options and precision.
    if (measureCells) {
        run("Clear Results");
        run("Set Measurements...", "area centroid perimeter fit shape feret's redirect=None decimal=3");
        roiManager("Measure");
        saveAs("Results", destination + "measurement.csv");
        run("Clear Results");
    }
    if (exportMasks) {
        maskDir = destination + "masks/";
        File.makeDirectory(maskDir);
        roi_count = roiManager("count");
        W = getWidth();
        H = getHeight();
        for (i = 0; i < roi_count; i++) {
            roiManager("select", i);
            Roi.getBounds(x, y, w, h);
            thres = 2;
            // Preserve the original border exclusion and inverted binary masks.
            if ((x > thres) && (y > thres) && (x + w < W - thres) && (y + h < H - thres)) {
                run("Create Mask");
                run("Invert");
                saveAs("PNG", maskDir + "mask_" + i + ".png");
                close();
            }
        }
    }
    close("*");
    roiManager("reset");
}
