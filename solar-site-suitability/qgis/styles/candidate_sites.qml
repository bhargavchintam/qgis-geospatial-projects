<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="Symbology|Labeling">
  <!-- Candidate sites (results/demo/candidate_sites.gpkg): graduated fill on capacity_mw, labelled with rank. -->
  <renderer-v2 type="graduatedSymbol" attr="capacity_mw" graduatedMethod="GraduatedColor" forceraster="0" enableorderby="0" symbollevels="0">
    <ranges>
      <range lower="0.000" upper="50.000" symbol="0" label="&lt; 50 MW" render="true"/>
      <range lower="50.000" upper="100.000" symbol="1" label="50 - 100 MW" render="true"/>
      <range lower="100.000" upper="250.000" symbol="2" label="100 - 250 MW" render="true"/>
      <range lower="250.000" upper="500.000" symbol="3" label="250 - 500 MW" render="true"/>
      <range lower="500.000" upper="100000.000" symbol="4" label="&gt; 500 MW" render="true"/>
    </ranges>
    <symbols>
      <symbol type="fill" name="0" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="255,255,204,255"/>
            <Option type="QString" name="outline_color" value="228,26,28,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="1" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="254,217,118,255"/>
            <Option type="QString" name="outline_color" value="228,26,28,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="2" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="254,153,41,255"/>
            <Option type="QString" name="outline_color" value="228,26,28,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="3" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="217,95,14,255"/>
            <Option type="QString" name="outline_color" value="228,26,28,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="4" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="153,52,4,255"/>
            <Option type="QString" name="outline_color" value="228,26,28,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
    <source-symbol>
      <symbol type="fill" name="0" alpha="0.85" clip_to_extent="1" force_rtl="0">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option type="QString" name="color" value="254,153,41,255"/>
            <Option type="QString" name="outline_color" value="228,26,28,255"/>
            <Option type="QString" name="outline_style" value="solid"/>
            <Option type="QString" name="outline_width" value="0.4"/>
            <Option type="QString" name="style" value="solid"/>
          </Option>
        </layer>
      </symbol>
    </source-symbol>
    <colorramp type="gradient" name="[source]">
      <Option type="Map">
        <Option type="QString" name="color1" value="255,255,204,255"/>
        <Option type="QString" name="color2" value="153,52,4,255"/>
        <Option type="QString" name="stops" value="0.5;254,153,41,255"/>
      </Option>
    </colorramp>
    <classificationMethod id="Custom">
      <symmetricMode enabled="0" symmetrypoint="0" astride="0"/>
      <labelFormat format="%1 - %2" labelprecision="0" trimtrailingzeroes="1"/>
      <parameters>
        <Option/>
      </parameters>
      <extraInformation/>
    </classificationMethod>
    <rotation/>
    <sizescale/>
  </renderer-v2>
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style fieldName="rank" isExpression="0" fontFamily="Open Sans" namedStyle="Bold" fontWeight="75" fontSize="10" fontSizeUnit="Point" textColor="255,255,255,255" textOpacity="1" fontItalic="0" fontUnderline="0" fontStrikeout="0" fontLetterSpacing="0" fontWordSpacing="0" multilineHeight="1" blendMode="0" previewBkgrdColor="255,255,255,255" allowHtml="0" capitalization="0" textOrientation="horizontal" useSubstitutions="0">
        <text-buffer bufferDraw="1" bufferSize="1.2" bufferSizeUnits="MM" bufferColor="228,26,28,255" bufferOpacity="1" bufferJoinStyle="128" bufferNoFill="1" bufferBlendMode="0"/>
        <text-mask maskEnabled="0" maskSize="0" maskType="0" maskJoinStyle="128" maskOpacity="1" maskSizeUnits="MM"/>
        <background shapeDraw="0" shapeType="0" shapeSizeType="0" shapeSizeX="0" shapeSizeY="0" shapeSizeUnit="MM" shapeRotationType="0" shapeRotation="0" shapeOffsetX="0" shapeOffsetY="0" shapeOffsetUnit="MM" shapeRadiiX="0" shapeRadiiY="0" shapeRadiiUnit="MM" shapeFillColor="255,255,255,255" shapeBorderColor="128,128,128,255" shapeBorderWidth="0" shapeBorderWidthUnit="MM" shapeJoinStyle="64" shapeOpacity="1" shapeBlendMode="0"/>
        <shadow shadowDraw="0" shadowUnder="0" shadowOffsetAngle="135" shadowOffsetDist="1" shadowOffsetUnit="MM" shadowOffsetGlobal="1" shadowRadius="1.5" shadowRadiusUnit="MM" shadowRadiusAlphaOnly="0" shadowScale="100" shadowColor="0,0,0,255" shadowOpacity="0.7" shadowBlendMode="6"/>
        <dd_properties>
          <Option type="Map">
            <Option type="QString" name="name" value=""/>
            <Option name="properties"/>
            <Option type="QString" name="type" value="collection"/>
          </Option>
        </dd_properties>
        <substitutions/>
      </text-style>
      <text-format formatNumbers="0" decimals="0" plussign="0" wrapChar="" autoWrapLength="0" useMaxLineLengthForAutoWrap="1" multilineAlign="3" leftDirectionSymbol="&lt;" rightDirectionSymbol="&gt;" placeDirectionSymbol="0" reverseDirectionSymbol="0" addDirectionSymbol="0"/>
      <placement placement="4" centroidInside="1" centroidWhole="0" fitInPolygonOnly="0" polygonPlacementFlags="2" quadOffset="4" xOffset="0" yOffset="0" offsetType="0" offsetUnits="MM" dist="0" distUnits="MM" priority="5" placementFlags="10" rotationAngle="0" rotationUnit="AngleDegrees" preserveRotation="1" repeatDistance="0" repeatDistanceUnits="MM" overrunDistance="0" overrunDistanceUnit="MM" lineAnchorPercent="0.5" lineAnchorType="0" lineAnchorClipping="0" lineAnchorTextPoint="CenterOfText" maxCurvedCharAngleIn="25" maxCurvedCharAngleOut="-25" geometryGenerator="" geometryGeneratorEnabled="0" geometryGeneratorType="PointGeometry" layerType="PolygonGeometry" overlapHandling="PreventOverlap" allowDegraded="0"/>
      <rendering drawLabels="1" displayAll="0" scaleVisibility="0" scaleMin="0" scaleMax="0" fontLimitPixelSize="0" fontMinPixelSize="3" fontMaxPixelSize="10000" upsidedownLabels="0" limitNumLabels="0" maxNumLabels="2000" minFeatureSize="0" obstacle="1" obstacleFactor="1" obstacleType="1" zIndex="0" mergeLines="0" labelPerPart="0" unplacedVisibility="0"/>
      <dd_properties>
        <Option type="Map">
          <Option type="QString" name="name" value=""/>
          <Option name="properties"/>
          <Option type="QString" name="type" value="collection"/>
        </Option>
      </dd_properties>
      <callout type="simple">
        <Option type="Map">
          <Option type="QString" name="anchorPoint" value="pole_of_inaccessibility"/>
          <Option type="int" name="blendMode" value="0"/>
          <Option type="Map" name="ddProperties">
            <Option type="QString" name="name" value=""/>
            <Option name="properties"/>
            <Option type="QString" name="type" value="collection"/>
          </Option>
          <Option type="bool" name="drawToAllParts" value="false"/>
          <Option type="QString" name="enabled" value="0"/>
          <Option type="QString" name="labelAnchorPoint" value="point_on_exterior"/>
          <Option type="QString" name="lineSymbol" value=""/>
          <Option type="double" name="minLength" value="0"/>
          <Option type="QString" name="minLengthMapUnitScale" value="3x:0,0,0,0,0,0"/>
          <Option type="QString" name="minLengthUnit" value="MM"/>
          <Option type="double" name="offsetFromAnchor" value="0"/>
          <Option type="QString" name="offsetFromAnchorMapUnitScale" value="3x:0,0,0,0,0,0"/>
          <Option type="QString" name="offsetFromAnchorUnit" value="MM"/>
          <Option type="double" name="offsetFromLabel" value="0"/>
          <Option type="QString" name="offsetFromLabelMapUnitScale" value="3x:0,0,0,0,0,0"/>
          <Option type="QString" name="offsetFromLabelUnit" value="MM"/>
        </Option>
      </callout>
    </settings>
  </labeling>
  <layerGeometryType>2</layerGeometryType>
</qgis>
